from django.db import models
from django.conf import settings

class Absence(models.Model):
    # --- CHOIX POUR LE JURY ---
    TYPE_CHOICES = [
        ('HEURE', 'Heure'),
        ('SEANCE', 'Séance'),
        ('JOURNEE', 'Journée'),
    ]

    STATUT_CHOICES = [
        ('EN_ATTENTE', 'En attente'),
        ('JUSTIFIEE', 'Justifiée'),
        ('NON_JUSTIFIEE', 'Non justifiée'),
    ]

    # --- CHAMPS ---
    id_absence = models.AutoField(primary_key=True)
    id_inscription = models.ForeignKey(
        'enrollments.Inscription', 
        models.DO_NOTHING, 
        db_column='id_inscription',
        verbose_name="Inscription liée"
    )
    id_seance = models.ForeignKey(
        'academic_sessions.Seance', 
        models.DO_NOTHING, 
        db_column='id_seance',
        verbose_name="Séance concernée"
    )
    type_absence = models.CharField(
        max_length=20, 
        choices=TYPE_CHOICES, # Ajout des choix
        default='SEANCE'
    )
    duree_absence = models.FloatField(verbose_name="Durée (h)")
    statut = models.CharField(
        max_length=20, 
        choices=STATUT_CHOICES, # Ajout des choix
        default='EN_ATTENTE'
    )
    encodee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.DO_NOTHING, 
        db_column='encodee_par',
        verbose_name="Agent ayant encodé"
    )

    class Meta:
        managed = False
        db_table = 'absence'
        app_label = 'absences'
        verbose_name = "Absence"
        verbose_name_plural = "Absences"

    def __str__(self):
        return f"Absence de {self.id_inscription.id_etudiant} - {self.id_seance.date_seance}"


class Justification(models.Model):
    id_justification = models.AutoField(primary_key=True)
    id_absence = models.OneToOneField(
        Absence, 
        models.DO_NOTHING, 
        db_column='id_absence',
        verbose_name="Absence à justifier"
    )
    document = models.BinaryField(blank=True, null=True, verbose_name="Fichier (BLOB)")
    commentaire = models.TextField(blank=True, null=True)
    validee = models.BooleanField(default=False)
    validee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.DO_NOTHING, 
        db_column='validee_par', 
        blank=True, 
        null=True,
        verbose_name="Validée par"
    )
    date_validation = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'justification'
        app_label = 'absences'
        verbose_name = "Justification"
        verbose_name_plural = "Justifications"

    def __str__(self):
        return f"Justification pour l'absence n°{self.id_absence.id_absence}"