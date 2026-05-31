"""
Modèles de séances académiques pour le système UniAbsences.

Ce module définit les deux modèles temporels qui ancrent tous les
enregistrements de présence : l'année académique et la séance de cours
individuelle.

Modèles
-------
``AnneeAcademique``
    Représente une année académique (ex. « 2024-2025 »). Une seule année
    peut être active à la fois, garanti par un index unique partiel sur
    l'indicateur ``active``. Tous les calculs de taux d'absence sont
    rattachés à l'année active par défaut.

``Seance``
    Représente une séance de cours planifiée pour un cours donné.
    Contraintes :
    - Unicité : une séance par cours et par date.
    - La durée est stockée en flottant décimal (heures) et exposée via
      ``duree_display`` dans un format lisible « 2h30 ».
    - Les séances peuvent être verrouillées (``verrouille = True``) par
      un professeur ou une secrétaire après la finalisation de la
      présence ; les séances verrouillées ne peuvent plus être modifiées.

Fait partie de la structure académique d'UniAbsences.
"""

from datetime import datetime, timedelta

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


# ========================================================================== #
#                          ANNEE ACADEMIQUE                                  #
# ========================================================================== #


class AnneeAcademique(models.Model):
    """
    Représente une année académique (ex. « 2024-2025 »).

    Une seule année peut être marquée ``active = True`` à la fois. Cet
    invariant est garanti à deux niveaux :

    * **Base de données** : une ``UniqueConstraint`` partielle sur
      ``active`` où ``active = True`` empêche les lignes actives
      concurrentes.
    * **Application** : ``clean()`` lève ``ValidationError`` si une autre
      année active existe ; ``save()`` désactive toutes les autres années
      avant de persister la courante dans une transaction atomique.

    Effets de bord de l'activation/désactivation (gérés dans ``save()``)
    --------------------------------------------------------------------
    - *Activer* une année passe atomiquement toutes les autres années à
      ``active = False`` avant l'enregistrement.
    - *Désactiver* une année fait passer toutes les inscriptions
      ``EN_COURS`` de cette année à ``NON_VALIDE``, empêchant toute
      modification ultérieure sur une année académique close.

    Attributs
    ---------
    id_annee : int
        Clé primaire auto-incrémentée.
    libelle : str
        Libellé lisible au format recommandé « AAAA-AAAA »
        (ex. « 2024-2025 »). Doit être unique parmi toutes les années.
    active : bool
        Indique si c'est l'année académique actuellement active. Une
        seule ligne au maximum peut avoir ``active = True`` à un moment
        donné.
    """

    id_annee = models.AutoField(primary_key=True)
    libelle = models.CharField(
        unique=True,
        max_length=20,
        verbose_name="Libellé (ex: 2023-2024)",
        db_index=True,
        help_text="Format recommandé: AAAA-AAAA",
    )
    active = models.BooleanField(
        default=False,
        verbose_name="Année en cours ?",
        db_index=True,
        help_text="Une seule année peut être active à la fois",
    )

    class Meta:
        """Métadonnées Django : table ``annee_academique`` et contrainte d'unicité partielle sur ``active``."""

        managed = True
        db_table = "annee_academique"
        app_label = "academic_sessions"
        verbose_name = "Année Académique"
        verbose_name_plural = "Années Académiques"
        ordering = ["-libelle"]
        # Contrainte unique partielle pour garantir une seule année active
        constraints = [
            models.UniqueConstraint(
                fields=["active"],
                condition=models.Q(active=True),
                name="unique_active_annee_academique",
            )
        ]

    def clean(self):
        """
        Valide qu'au plus une année académique est active à la fois.

        Cette méthode est appelée par ``save()`` via ``full_clean()``
        après que les années concurrentes ont déjà été désactivées dans
        la même transaction atomique ; le contrôle ici sert principalement
        de filet de sécurité pour les soumissions de formulaire directes
        qui contournent ``save()``.

        Lève
        ----
        ValidationError
            Si une autre ligne ``AnneeAcademique`` possède déjà
            ``active=True``.
        """
        if self.active:
            # Exclut l'instance courante pour qu'un enregistrement sur place
            # ne déclenche pas un faux conflit avec elle-même.
            other_active = AnneeAcademique.objects.filter(active=True).exclude(
                pk=self.pk
            )
            if other_active.exists():
                raise ValidationError(
                    "Une autre année académique est déjà active. "
                    "Désactivez-la avant d'activer celle-ci."
                )

    def save(self, *args, **kwargs):
        """
        Persiste l'année académique en garantissant l'invariant d'unicité de l'année active.

        L'ensemble du travail est encapsulé dans ``transaction.atomic()``
        afin que toute erreur (ex. une ``ValidationError`` de
        ``full_clean()``) annule l'intégralité de l'opération, y compris
        toute mise à jour de masse déjà appliquée.

        Flux d'activation (``active`` passe de ``False`` à ``True``)
        ------------------------------------------------------------
        1. Toutes les autres lignes ``AnneeAcademique`` sont mises à
           ``active=False`` par mise à jour de masse *avant* l'exécution
           de ``full_clean()``, afin que ``clean()`` ne voie plus
           d'année active concurrente.
        2. ``full_clean()`` est appelé pour valider les champs du modèle.
        3. La ligne est enregistrée via ``super().save()``.

        Flux de désactivation (``active`` passe de ``True`` à ``False``)
        ----------------------------------------------------------------
        1. Tous les enregistrements ``Inscription`` de cette année dont
           le ``status`` vaut ``"EN_COURS"`` sont mis à ``"NON_VALIDE"``
           par mise à jour de masse, clôturant l'année académique pour
           les besoins d'inscription.
        2. ``full_clean()`` + ``super().save()`` persistent le changement.

        Paramètres
        ----------
        *args, **kwargs
            Transmis tels quels à ``Model.save()``.
        """
        with transaction.atomic():
            deactivating = False
            activating = False

            if self.pk:
                # Lit la valeur actuellement persistée pour détecter une transition d'état.
                old_active = (
                    AnneeAcademique.objects.filter(pk=self.pk)
                    .values_list("active", flat=True)
                    .first()
                )
                if old_active and not self.active:
                    # Transition de actif → inactif
                    deactivating = True
                elif not old_active and self.active:
                    # Transition de inactif → actif
                    activating = True
            elif self.active:
                # Toute nouvelle ligne déjà active
                activating = True

            if activating:
                # Désactive toutes les autres années AVANT full_clean() pour
                # que clean() ne lève pas d'erreur de conflit pour cette ligne.
                # Tout le bloc est atomique : il est annulé en cas d'erreur.
                AnneeAcademique.objects.exclude(pk=self.pk).update(active=False)

            if deactivating:
                # Clôture toutes les inscriptions en cours de l'année désactivée.
                # L'usage de apps.get_model() évite un import circulaire entre
                # les packages academic_sessions et enrollments.
                Inscription = apps.get_model("enrollments", "Inscription")
                Inscription.objects.filter(
                    id_annee=self, status="EN_COURS"
                ).update(status="NON_VALIDE")

            self.full_clean()
            super().save(*args, **kwargs)

    def __str__(self):
        """Retourne le libellé de l'année (ex. « 2024-2025 ») comme représentation textuelle."""
        return self.libelle


# ========================================================================== #
#                          SEANCE DE COURS                                   #
# ========================================================================== #


class Seance(models.Model):
    """
    Représente une séance de cours planifiée pour un cours donné.

    Une séance est identifiée de manière unique par son cours et sa date
    (contrainte ``unique_seance_par_cours_date``). La durée est dérivée
    de ``heure_debut`` et ``heure_fin`` et exposée via deux utilitaires :
    ``duree_heures()`` (heures décimales) et ``duree_formatee()`` (chaîne
    lisible telle que « 2h30 »).

    Une séance peut être *validée* par une secrétaire ou un professeur
    après la finalisation de la présence. Une fois validée
    (``validated=True``), la liste de présence est verrouillée et ne peut
    plus être modifiée par un enseignant.

    Attributs
    ---------
    id_seance : int
        Clé primaire auto-incrémentée.
    date_seance : date
        Date calendaire de la séance.
    heure_debut : time
        Heure de début de la séance.
    heure_fin : time
        Heure de fin de la séance (doit être strictement après ``heure_debut``).
    id_cours : Cours
        Le cours auquel cette séance appartient (PROTECT).
    id_annee : AnneeAcademique
        Année académique à laquelle cette séance est rattachée (PROTECT).
    validated : bool
        Indique si la présence de la séance a été finalisée et verrouillée.
    validated_by : User ou None
        L'utilisateur qui a validé la séance (SET_NULL — préservé si
        l'utilisateur est supprimé).
    date_validated : datetime ou None
        Horodatage UTC de la validation.
    """

    id_seance = models.AutoField(primary_key=True)
    date_seance = models.DateField(verbose_name="Date de la séance", db_index=True)
    heure_debut = models.TimeField(verbose_name="Heure début")
    heure_fin = models.TimeField(verbose_name="Heure fin")
    id_cours = models.ForeignKey(
        "academics.Cours",
        models.PROTECT,  # Empêche la suppression d'un cours avec des séances
        db_column="id_cours",
        verbose_name="Cours",
        related_name="seances",
    )
    id_annee = models.ForeignKey(
        AnneeAcademique,
        models.PROTECT,  # Empêche la suppression d'une année avec des séances
        db_column="id_annee",
        verbose_name="Année académique",
        related_name="seances",
    )
    validated = models.BooleanField(
        default=False,
        verbose_name="Séance validée",
        help_text="Une fois validée, la présence ne peut plus être modifiée par le professeur.",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Validée par",
        related_name="seances_validees",
    )
    date_validated = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date de validation",
    )

    class Meta:
        """Métadonnées Django : table ``seance``, index, unicité (cours, date) et contrainte d'horaires."""

        managed = True
        db_table = "seance"
        app_label = "academic_sessions"
        verbose_name = "Séance"
        verbose_name_plural = "Séances"
        ordering = ["-date_seance", "-heure_debut"]
        indexes = [
            models.Index(fields=["id_cours", "date_seance"]),
            models.Index(fields=["id_annee", "date_seance"]),
            models.Index(
                fields=["id_cours", "id_annee", "date_seance", "heure_debut"],
                name="seance_cours_annee_dt_h_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["id_cours", "date_seance"],
                name="unique_seance_par_cours_date",
            ),
            models.CheckConstraint(
                condition=models.Q(heure_fin__gt=models.F("heure_debut")),
                name="seance_heure_fin_after_debut",
            ),
        ]

    def clean(self):
        """
        Valide que l'heure de fin de séance est strictement postérieure à l'heure de début.

        Lève
        ----
        ValidationError
            Si ``heure_fin`` est inférieure ou égale à ``heure_debut``.
        """
        if self.heure_debut and self.heure_fin:
            if self.heure_fin <= self.heure_debut:
                raise ValidationError(
                    "L'heure de fin doit être après l'heure de début."
                )

    def save(self, *args, **kwargs):
        """
        Valide la séance avant la persistance.

        Appelle ``full_clean()`` pour appliquer les contraintes au niveau
        du modèle (notamment la vérification ``heure_fin > heure_debut``)
        avant de déléguer au ``save()`` standard de Django.

        Paramètres
        ----------
        *args, **kwargs
            Transmis tels quels à ``Model.save()``.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def duree_heures(self):
        """
        Retourne la durée de la séance en heures décimales.

        Les valeurs de ``TimeField`` ne peuvent pas être soustraites
        directement en Python ; les deux heures sont donc combinées avec
        une date de référence arbitraire (2000-01-01) pour créer des
        objets ``datetime`` complets avant de calculer la différence. Si
        ``heure_fin`` précède ``heure_debut`` (séance traversant minuit),
        un jour est ajouté à ``fin`` pour garder une différence positive.

        Retourne
        --------
        float
            Durée en heures, arrondie à deux décimales.
            Retourne ``0.0`` si l'un des champs d'heure est non défini.

        Exemples
        --------
        08:30 → 10:30  =>  2.0
        08:00 → 09:30  =>  1.5
        """
        if not self.heure_debut or not self.heure_fin:
            return 0.0

        # Combine les champs d'heure avec une date de référence fixe pour permettre la soustraction
        date_ref = datetime(2000, 1, 1)
        debut = datetime.combine(date_ref, self.heure_debut)
        fin = datetime.combine(date_ref, self.heure_fin)

        # Gère le cas particulier d'une séance traversant minuit
        if fin < debut:
            fin += timedelta(days=1)

        delta = fin - debut
        duree_heures = delta.total_seconds() / 3600.0

        return round(duree_heures, 2)

    def duree_formatee(self):
        """
        Retourne la durée de la séance sous forme de chaîne lisible.

        Utilise la même astuce de date de référence que ``duree_heures()``
        pour convertir les champs ``TimeField`` en ``datetime`` soustrayables,
        puis met en forme le résultat selon trois cas :

        - Heures pleines uniquement  → ``"2h"``
        - Minutes uniquement         → ``"30min"``
        - Heures et minutes          → ``"2h30"``

        Retourne
        --------
        str
            Chaîne représentant la durée (ex. « 2h », « 2h30 », « 45min »).
            Retourne ``"0h"`` si l'un des champs d'heure n'est pas défini.

        Exemples
        --------
        08:00 → 10:00  =>  "2h"
        08:00 → 08:30  =>  "30min"
        08:00 → 09:45  =>  "1h45"
        """
        if not self.heure_debut or not self.heure_fin:
            return "0h"

        # Combine les champs d'heure avec une date de référence fixe pour permettre la soustraction
        date_ref = datetime(2000, 1, 1)
        debut = datetime.combine(date_ref, self.heure_debut)
        fin = datetime.combine(date_ref, self.heure_fin)

        # Gère le cas particulier d'une séance traversant minuit
        if fin < debut:
            fin += timedelta(days=1)

        # Convertit le delta total en nombre entier de minutes
        delta = fin - debut
        total_minutes = int(delta.total_seconds() / 60)

        # Décompose en heures et minutes restantes
        heures = total_minutes // 60
        minutes = total_minutes % 60

        # Sélectionne le format adapté
        if heures == 0:
            return f"{minutes}min"
        elif minutes == 0:
            return f"{heures}h"
        else:
            return f"{heures}h{minutes:02d}"

    def __str__(self):
        """Retourne le nom du cours, la date et l'heure de début comme libellé compact."""
        return f"{self.id_cours.nom_cours} - {self.date_seance} ({self.heure_debut})"
