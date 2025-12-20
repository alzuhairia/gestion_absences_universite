from django.db import models

class Faculte(models.Model):
    id_faculte = models.AutoField(primary_key=True)
    nom_faculte = models.CharField(
        unique=True, 
        max_length=200, 
        verbose_name="Nom de la faculté"
    )

    class Meta:
        managed = False
        db_table = 'faculte'
        app_label = 'academics'
        verbose_name = "Faculté"
        verbose_name_plural = "Facultés"

    def __str__(self):
        return self.nom_faculte


class Departement(models.Model):
    id_departement = models.AutoField(primary_key=True)
    nom_departement = models.CharField(
        max_length=200, 
        verbose_name="Nom du département"
    )
    id_faculte = models.ForeignKey(
        Faculte, 
        models.DO_NOTHING, 
        db_column='id_faculte',
        verbose_name="Faculté de rattachement"
    )

    class Meta:
        managed = False
        db_table = 'departement'
        app_label = 'academics'
        verbose_name = "Département"
        verbose_name_plural = "Départements"

    def __str__(self):
        return f"{self.nom_departement} ({self.id_faculte.nom_faculte})"


class Cours(models.Model):
    id_cours = models.AutoField(primary_key=True)
    code_cours = models.CharField(
        unique=True, 
        max_length=50, 
        verbose_name="Code du cours"
    )
    nom_cours = models.CharField(
        max_length=200, 
        verbose_name="Intitulé du cours"
    )
    nombre_total_periodes = models.IntegerField(
        verbose_name="Total périodes (h)"
    )
    seuil_absence = models.IntegerField(
        blank=True, 
        null=True, 
        default=40,
        verbose_name="Seuil d'absence (%)"
    )
    id_departement = models.ForeignKey(
        Departement, 
        models.DO_NOTHING, 
        db_column='id_departement',
        verbose_name="Département"
    )

    class Meta:
        managed = False
        db_table = 'cours'
        app_label = 'academics'
        verbose_name = "Cours"
        verbose_name_plural = "Cours"

    def __str__(self):
        return f"[{self.code_cours}] {self.nom_cours}"