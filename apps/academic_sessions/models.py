from django.db import models

class AnneeAcademique(models.Model):
    id_annee = models.AutoField(primary_key=True)
    libelle = models.CharField(
        unique=True, 
        max_length=20, 
        verbose_name="Libellé (ex: 2023-2024)"
    )
    active = models.BooleanField(
        default=False, 
        verbose_name="Année en cours ?"
    )

    class Meta:
        managed = True
        db_table = 'annee_academique'
        app_label = 'academic_sessions'
        verbose_name = "Année Académique"
        verbose_name_plural = "Années Académiques"

    def __str__(self):
        return self.libelle


class Seance(models.Model):
    id_seance = models.AutoField(primary_key=True)
    date_seance = models.DateField(verbose_name="Date de la séance")
    heure_debut = models.TimeField(verbose_name="Heure début")
    heure_fin = models.TimeField(verbose_name="Heure fin")
    id_cours = models.ForeignKey(
        'academics.Cours', 
        models.DO_NOTHING, 
        db_column='id_cours',
        verbose_name="Cours"
    )
    id_annee = models.ForeignKey(
        AnneeAcademique, 
        models.DO_NOTHING, 
        db_column='id_annee',
        verbose_name="Année académique"
    )

    class Meta:
        managed = True
        db_table = 'seance'
        app_label = 'academic_sessions'
        verbose_name = "Séance"
        verbose_name_plural = "Séances"

    def __str__(self):
        return f"{self.id_cours.nom_cours} - {self.date_seance} ({self.heure_debut})"
