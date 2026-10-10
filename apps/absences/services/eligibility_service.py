"""
Service d'éligibilité aux examens et calcul du risque — apps/absences/services/eligibility_service.py

Fait partie du système universitaire de gestion des présences UniAbsences.

Ce module est la source de vérité de référence pour l'éligibilité aux examens
et le statut de risque d'absence à l'échelle du système. Toute vue, signal ou
endpoint d'API ayant besoin de déterminer si un étudiant est bloqué à un
examen doit appeler les fonctions d'ici plutôt que de dupliquer la logique.

Principales responsabilités :
  - ``recalculer_eligibilite``         : décide (et persiste) si un étudiant est bloqué
  - ``calculer_risque_inscription``    : retourne le profil de risque complet pour une inscription
  - ``get_at_risk_count_for_queryset`` : compte en lot des inscriptions à risque pour les tableaux de bord

Règle métier centrale :
  Un étudiant est bloqué si son taux d'absence NON_JUSTIFIEE >= le seuil effectif.

  Seuil effectif = seuil du cours + marge d'exemption
      (si une exemption a été accordée à l'étudiant ; sinon = seuil du cours).

Déclenchement automatique :
  ``recalculer_eligibilite`` est appelé par le signal ``post_save`` sur ``Absence``
  afin que chaque création ou mise à jour d'absence ré-évalue immédiatement
  l'éligibilité.
"""
import logging
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audits.models import LogAudit
from apps.notifications.email import (
    build_eligibility_restored_email,
    build_threshold_exceeded_email,
    build_threshold_exceeded_professor_email,
    send_notification_email,
)
from apps.notifications.models import Notification

from ..models import Absence
from .absence_service import calculer_absence_stats

logger = logging.getLogger(__name__)


def get_system_threshold():
    """
    Récupère le seuil d'absence par défaut au niveau système depuis ``SystemSettings``.

    Utilisé comme repli quand un cours n'a pas de seuil personnel configuré.
    La valeur est récupérée en une seule requête à la base de données.

    Retour :
        int | float : seuil d'absence par défaut en pourcentage (ex. 20).
    """
    from apps.dashboard.models import SystemSettings

    return SystemSettings.get_settings().default_absence_threshold


def recalculer_eligibilite(inscription):
    """
    Recalcule et persiste le statut d'éligibilité à l'examen pour une inscription.

    C'est la fonction de décision centrale du système UniAbsences.

    Algorithme :
      1. Calcule les statistiques d'absence courantes via ``calculer_absence_stats``.
      2. Détermine le seuil effectif (seuil du cours + marge d'exemption si
         une exemption est active).
      3. Si taux >= seuil effectif ET étudiant actuellement éligible →
         bloque l'étudiant, envoie les notifications et écrit un log d'audit CRITIQUE.
      4. Si taux < seuil effectif ET étudiant actuellement bloqué →
         restaure l'éligibilité et notifie l'étudiant par email.

    Toutes les écritures en base sont englobées dans ``transaction.atomic()``
    pour garantir que le drapeau d'éligibilité et la notification soient soit
    tous les deux sauvegardés, soit aucun. Les emails sont envoyés via
    ``transaction.on_commit`` afin qu'un échec SMTP ne puisse pas annuler la
    transaction de base de données.

    Args :
        inscription : instance ``apps.enrollments.models.Inscription`` à
            ré-évaluer. Le ``id_cours`` relié doit être accessible.

    Effets de bord :
      - Peut mettre à jour ``inscription.eligible_examen`` et la sauvegarder.
      - Peut créer une ``Notification`` pour l'étudiant.
      - Peut créer une entrée ``LogAudit`` de niveau CRITIQUE.
      - Peut envoyer des emails à l'étudiant et/ou au professeur du cours.
    """
    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]
    total_periodes = stats["total_periodes"]
    cours = inscription.id_cours

    # Aucune séance encore planifiée → l'étudiant ne peut pas être bloqué ; s'assurer que le drapeau vaut True.
    if total_periodes == 0:
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=["eligible_examen"])
        return

    seuil = cours.get_seuil_absence()
    # Les étudiants exemptés bénéficient d'une marge supplémentaire avant d'être bloqués.
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil
    doit_bloquer = taux >= seuil_effectif

    if doit_bloquer:
        # N'agir que si l'étudiant était précédemment éligible (éviter les notifications en doublon).
        if inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = False
                inscription.save(update_fields=["eligible_examen"])

                # Construit le message de notification — distinguer étudiants exemptés et non exemptés.
                msg = (
                    f"ALERTE : Seuil d'exemption de {seuil_effectif}% dépassé pour {cours.nom_cours}. "
                    f"Examen bloqué malgré l'exemption."
                    if inscription.exemption_40
                    else f"ALERTE : Seuil de {seuil}% dépassé pour {cours.nom_cours}. Examen bloqué."
                )
                try:
                    Notification.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        message=msg,
                        type="ALERTE",
                    )
                except Exception:
                    logger.exception("Échec de création de la notification de blocage pour %s", cours.nom_cours)

                # Capturer les références maintenant ; les closures dans on_commit capturent par référence
                # et la variable de boucle serait obsolète au moment où le callback s'exécute.
                student = inscription.id_etudiant
                professor = cours.professeur
                course_name = cours.nom_cours
                transaction.on_commit(
                    lambda: _send_threshold_emails(student, professor, course_name, taux, seuil_effectif)
                )

                # Écrit une entrée d'audit CRITIQUE pour que les administrateurs puissent tracer chaque blocage.
                try:
                    LogAudit.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        action=(
                            f"CRITIQUE: Blocage automatique examen - {cours.nom_cours} "
                            f"(Taux: {taux:.1f}%, Seuil effectif: {seuil_effectif}%"
                            f"{', exempté' if inscription.exemption_40 else ''})"
                        ),
                        adresse_ip="0.0.0.0",  # nosec B104 — événement système, pas de vraie IP
                        niveau="CRITIQUE",
                        objet_type="INSCRIPTION",
                        objet_id=inscription.id_inscription,
                    )
                except Exception:
                    logger.exception("Échec de création du log d'audit de blocage pour %s", cours.nom_cours)
    else:
        # Le taux d'absence est sous le seuil — restaure l'éligibilité si l'étudiant était bloqué.
        if not inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = True
                inscription.save(update_fields=["eligible_examen"])

                try:
                    Notification.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        message=f"Information : Vous êtes à nouveau éligible à l'examen pour {cours.nom_cours}.",
                        type="INFO",
                    )
                except Exception:
                    logger.exception("Échec de création de la notification de déblocage pour %s", cours.nom_cours)

                student = inscription.id_etudiant
                course_name = cours.nom_cours

                def _send_restored():
                    """Envoie l'email de restauration d'éligibilité après le commit de la transaction."""
                    subj, body, html_body = build_eligibility_restored_email(student, course_name)
                    send_notification_email(student, subj, body, html_body)

                transaction.on_commit(_send_restored)


def _send_threshold_emails(student, professor, course_name, taux, seuil):
    """
    Envoie les emails de notification de seuil dépassé à l'étudiant et au professeur.

    Cette fonction est appelée via ``transaction.on_commit`` afin que les échecs
    SMTP n'annulent pas le changement d'éligibilité en base.

    Args :
        student : instance ``User`` de l'étudiant bloqué.
        professor : instance ``User`` du professeur du cours, ou None.
        course_name (str) : nom lisible du cours pour le contenu de l'email.
        taux (float) : taux d'absence courant en pourcentage.
        seuil (float) : seuil effectif qui a été dépassé.

    Effets de bord :
        Envoie jusqu'à deux emails (étudiant + professeur). Les exceptions sont
        capturées et journalisées afin qu'un email en échec n'apparaisse pas
        comme une HTTP 500.
    """
    try:
        subj, body, html_body = build_threshold_exceeded_email(student, course_name, taux, seuil)
        send_notification_email(student, subj, body, html_body)
        if professor:
            subj, body, html_body = build_threshold_exceeded_professor_email(
                professor, student, course_name, taux, seuil
            )
            send_notification_email(professor, subj, body, html_body)
    except Exception:
        logger.exception("Échec d'envoi des emails de seuil pour %s", course_name)


def calculer_risque_inscription(inscription, system_threshold=None):
    """
    Retourne le profil de risque complet pour une seule inscription.

    Cette fonction est la source de vérité unique pour le statut de risque
    utilisé par toutes les vues et API. Elle consolide la logique qui était
    auparavant dupliquée dans plus de 8 fonctions de vue.

    Args :
        inscription : instance ``apps.enrollments.models.Inscription``.
        system_threshold (int | float | None) : seuil système par défaut pré-chargé.
            Si None, il est récupéré via ``get_system_threshold()``.

    Retour :
        dict avec les clés suivantes :

        - ``is_at_risk`` (bool) : True si le taux atteint le seuil de base du cours.
        - ``is_blocked`` (bool) : True si le taux atteint le seuil effectif
          (après application de toute marge d'exemption).
        - ``is_under_exemption`` (bool) : True si l'étudiant est à risque mais pas encore
          bloqué parce qu'une marge d'exemption le protège.
        - ``taux`` (float) : taux d'absence courant, arrondi à 1 décimale.
        - ``seuil`` (int | float) : seuil de base du cours.
        - ``seuil_effectif`` (int | float) : seuil effectif après exemption.
        - ``total_absence`` (float) : total des heures d'absence non justifiée.
        - ``total_periodes`` (int) : total des heures de cours prévues.
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    cours = inscription.id_cours
    # Utilise le seuil spécifique au cours quand il est défini ; repli sur le défaut système.
    seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil

    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]

    is_at_risk = taux >= seuil
    is_blocked = taux >= seuil_effectif
    # Sous exemption : l'étudiant a franchi le seuil de base mais est encore protégé
    # par la marge d'exemption — il doit être averti mais n'est pas encore bloqué.
    is_under_exemption = inscription.exemption_40 and is_at_risk and not is_blocked

    return {
        "is_at_risk": is_at_risk,
        "is_blocked": is_blocked,
        "is_under_exemption": is_under_exemption,
        "taux": round(taux, 1),
        "seuil": seuil,
        "seuil_effectif": seuil_effectif,
        "total_absence": stats["total_absence"],
        "total_periodes": stats["total_periodes"],
    }


def get_at_risk_count_for_queryset(inscriptions_qs, system_threshold=None):
    """
    Compte le nombre d'inscriptions à risque dans un queryset.

    Optimisé pour les vues de tableau de bord : effectue une seule agrégation SQL
    en lot au lieu d'évaluer chaque inscription individuellement. Cela garde
    les temps de chargement de page acceptables même pour de grosses cohortes.

    Args :
        inscriptions_qs : ``QuerySet[Inscription]`` — l'ensemble des inscriptions
            à examiner. Le ``id_cours`` relié doit être accessible (utilisez
            ``select_related("id_cours")`` avant de passer).
        system_threshold (int | float | None) : seuil système par défaut pré-chargé.
            Réutilisez une valeur en cache ici lors d'un appel en boucle pour
            éviter un appel à la base par inscription.

    Retour :
        tuple :
          - ``at_risk_count`` (int) : nombre d'inscriptions dont le taux
            d'absence effectif atteint ou dépasse le seuil effectif.
          - ``absence_sums`` (dict) : table ``{id_inscription: total_heures}``
            pour toutes les inscriptions ayant des absences non justifiées
            enregistrées à ce jour. Les appelants peuvent réutiliser ce dict
            pour éviter des requêtes en doublon.
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    inscription_ids = list(inscriptions_qs.values_list("id_inscription", flat=True))
    if not inscription_ids:
        return 0, {}

    today = timezone.localdate()

    # Une seule requête d'agrégation : somme des heures d'absence non justifiée par inscription.
    absence_sums: dict[int, Any] = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    at_risk_count = 0
    for ins in inscriptions_qs:
        cours = ins.id_cours
        # Ignore les inscriptions sans heures planifiées — elles ne peuvent pas être à risque.
        if not cours.nombre_total_periodes:
            continue
        seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0
        taux = min((total_abs / cours.nombre_total_periodes) * 100, 100)
        # Applique la marge d'exemption avant de comparer au seuil.
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
        if taux >= seuil_effectif:
            at_risk_count += 1

    return at_risk_count, absence_sums
