"""
Vue d'export Excel pour le tableau de bord administrateur / secrétaire UniAbsences.

Ce module expose une vue unique qui diffuse un classeur openpyxl en tant que
réponse HTTP de type
``application/vnd.openxmlformats-officedocument.spreadsheetml.sheet``.

``export_at_risk_excel``
    Génère un classeur listant tous les étudiants dont le taux d'absence non
    justifiée atteint ou dépasse le seuil applicable au cours pour l'année
    académique active. Chaque ligne inclut l'identité de l'étudiant, le cours,
    les heures manquées, le taux d'absence et un libellé de statut
    (BLOQUÉ / EXEMPTÉ).

    L'accès est réservé aux rôles administrateur et secrétaire via
    ``@secretary_required``. Toutes les valeurs de cellules sont assainies
    avec ``excel_safe_cell`` pour empêcher les attaques par injection de
    formules CSV/Excel (valeurs commençant par =, +, -, @, etc.).

Fait partie du système de tableau de bord UniAbsences.
"""

from typing import cast

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from apps.absences.models import Absence
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription
from apps.utils import excel_safe_cell


@login_required
@secretary_required
@require_GET
def export_at_risk_excel(request):
    """
    Diffuse un classeur Excel listant tous les étudiants à risque pour l'année active.

    Le classeur contient une feuille ("Etudiants a Risque") avec les colonnes
    suivantes : Nom, Prenom, Email, Cours, Heures Manquees, Taux Absence (%),
    Statut.

    Une ligne étudiant est incluse lorsque son taux d'absence non justifiée est
    supérieur ou égal au seuil effectif du cours (``seuil_effectif``). Le seuil
    effectif prend l'override par cours (``Cours.seuil_absence``) ou la valeur
    par défaut du système, puis ajoute la marge d'exemption si l'étudiant
    bénéficie d'une exemption.

    Libellés de statut :
        - ``EXEMPTÉ``  — taux >= seuil de base mais inférieur au seuil
                         d'exemption rehaussé (étudiant temporairement protégé).
        - ``BLOQUÉ``   — taux >= seuil effectif (étudiant inéligible).

    L'action est enregistrée dans la piste d'audit après la construction du
    classeur.

    Paramètres
    ----------
    request : HttpRequest
        Doit être une requête GET d'un utilisateur administrateur ou secrétaire
        authentifié.

    Retourne
    --------
    HttpResponse
        Une réponse ``application/vnd.openxmlformats-officedocument.spreadsheetml.sheet``
        avec ``Content-Disposition: attachment``.
    """
    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="etudiants_a_risque.xlsx"'

    wb = Workbook()
    # cast() indique aux vérificateurs de types que wb.active est un Worksheet
    # complet, et non le WriteOnlyWorksheet plus restreint que openpyxl peut
    # retourner pour les modes optimisés.
    ws = cast(Worksheet, wb.active)
    ws.title = "Étudiants à Risque"

    # Ligne d'en-tête — l'ordre des colonnes doit correspondre aux lignes de
    # données ajoutées plus bas.
    columns = [
        "Nom",
        "Prénom",
        "Email",
        "Cours",
        "Heures Manquées",
        "Taux Absence (%)",
        "Statut",
    ]
    ws.append(columns)

    # Imports paresseux pour éviter les dépendances circulaires au chargement du module.
    from apps.absences.services import get_system_threshold
    from apps.academic_sessions.models import AnneeAcademique

    active_year = AnneeAcademique.objects.filter(active=True).first()

    # Récupère toutes les inscriptions EN_COURS, optionnellement filtrées sur
    # l'année active.
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if active_year:
        all_inscriptions = all_inscriptions.filter(id_annee=active_year)

    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    system_threshold = get_system_threshold()
    today = timezone.localdate()

    # Requête d'agrégation unique : somme les heures d'absence non justifiée
    # par inscription. Seules les séances antérieures ou égales à aujourd'hui
    # sont comptées afin que les séances futures ne gonflent pas le taux
    # prématurément.
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100

            # Détermine le seuil applicable : override du cours > défaut système.
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            # Le seuil effectif peut être relevé pour les étudiants exemptés
            # (flag exemption_40) en ajoutant leur exemption_margin personnel,
            # plafonné à 100 % pour ne jamais produire un seuil impossible.
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

            if rate >= seuil:
                # Détermine si l'exemption protège l'étudiant.
                if ins.exemption_40 and rate < seuil_effectif:
                    statut = "EXEMPTÉ"
                else:
                    statut = "BLOQUÉ"

                # All string cells are passed through excel_safe_cell to strip
                # or prefix any leading formula-trigger characters (=, +, -, @).
                ws.append([
                    excel_safe_cell(ins.id_etudiant.nom),
                    excel_safe_cell(ins.id_etudiant.prenom),
                    excel_safe_cell(ins.id_etudiant.email),
                    excel_safe_cell(f"{cours.nom_cours} ({cours.code_cours})"),
                    total_abs,
                    round(rate, 2),
                    statut,
                ])

    # Audit trail: log the export action for traceability.
    log_action(
        request.user,
        "Secrétaire a exporté la liste des étudiants à risque au format Excel",
        request,
        niveau="INFO",
        objet_type="EXPORT",
        objet_id=None,
    )

    wb.save(response)
    return response
