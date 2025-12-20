from django.db import models
from django.conf import settings

class Inscription(models.Model):
    # --- CHOIX ---
    TYPE_CHOICES = [
        ('NORMALE', 'Normale'),
        ('A_PART', 'À part'),
    ]

    # --- CHAMPS ---
    id_inscription = models.AutoField(primary_key=True)
    id_etudiant = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.DO_NOTHING, 
        db_column='id_etudiant',
        verbose_name="Étudiant"
    )
    id_cours = models.ForeignKey(
        'academics.Cours', 
        models.DO_NOTHING, 
        db_column='id_cours',
        verbose_name="Cours"
    )
    id_annee = models.ForeignKey(
        'academic_sessions.AnneeAcademique', 
        models.DO_NOTHING, 
        db_column='id_annee',
        verbose_name="Année Académique"
    )
    type_inscription = models.CharField(
        max_length=20, 
        choices=TYPE_CHOICES, 
        default='NORMALE',
        verbose_name="Type d'inscription"
    )
    eligible_examen = models.BooleanField(
        default=True, 
        verbose_name="Éligible examen ?"
    )

    class Meta:
        managed = False
        db_table = 'inscription'
        app_label = 'enrollments'
        unique_together = (('id_etudiant', 'id_cours', 'id_annee'),)
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"

    def __str__(self):
        return f"{self.id_etudiant.nom} {self.id_etudiant.prenom} -> {self.id_cours.nom_cours}"