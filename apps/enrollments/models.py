from django.db import models
from django.db.models import Sum
from django.conf import settings
from django.core.exceptions import ValidationError


class Inscription(models.Model):
    """
    Modèle représentant l'inscription d'un étudiant à un cours pour une année académique.
    """
    # --- CHOIX ---
    TYPE_CHOICES = [
        ('NORMALE', 'Normale'),
        ('A_PART', 'À part'),
    ]

    STATUS_CHOICES = [
        ('EN_COURS', 'En cours'),
        ('VALIDE', 'Validé'),
        ('NON_VALIDE', 'Non validé'),
    ]

    # --- CHAMPS ---
    id_inscription = models.AutoField(primary_key=True)
    id_etudiant = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.PROTECT,  # Empêche la suppression d'un étudiant avec des inscriptions
        db_column='id_etudiant',
        verbose_name="Étudiant",
        related_name='inscriptions',
        limit_choices_to={'role': 'ETUDIANT'}
    )
    id_cours = models.ForeignKey(
        'academics.Cours', 
        models.PROTECT,  # Empêche la suppression d'un cours avec des inscriptions
        db_column='id_cours',
        verbose_name="Cours",
        related_name='inscriptions'
    )
    id_annee = models.ForeignKey(
        'academic_sessions.AnneeAcademique', 
        models.PROTECT,  # Empêche la suppression d'une année avec des inscriptions
        db_column='id_annee',
        verbose_name="Année Académique",
        related_name='inscriptions'
    )
    type_inscription = models.CharField(
        max_length=20, 
        choices=TYPE_CHOICES, 
        default='NORMALE',
        verbose_name="Type d'inscription",
        db_index=True
    )
    eligible_examen = models.BooleanField(
        default=True, 
        verbose_name="Éligible examen ?",
        db_index=True,
        help_text="Calculé automatiquement selon le taux d'absences. Ne pas modifier manuellement."
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='EN_COURS',
        verbose_name="Statut",
        db_index=True
    )
    
    exemption_40 = models.BooleanField(
        default=False, 
        verbose_name="Exemption 40%",
        help_text="Si activé, l'étudiant est exempté du seuil de 40% d'absences"
    )
    motif_exemption = models.TextField(
        blank=True, 
        null=True, 
        verbose_name="Motif de l'exemption",
        help_text="Raison de l'exemption (obligatoire si exemption activée)"
    )

    class Meta:
        managed = True
        db_table = 'inscription'
        app_label = 'enrollments'
        unique_together = (('id_etudiant', 'id_cours', 'id_annee'),)
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        indexes = [
            models.Index(fields=['id_etudiant', 'id_annee', 'status']),
            models.Index(fields=['id_cours', 'id_annee', 'status']),
            models.Index(fields=['eligible_examen', 'status']),
        ]
        # Note: Les contraintes CHECK seront ajoutées via des migrations séparées

    def clean(self):
        """Validation: motif requis si exemption activée"""
        if self.exemption_40 and not self.motif_exemption:
            raise ValidationError({
                'motif_exemption': 'Un motif est obligatoire lorsque l\'exemption est activée.'
            })

    def save(self, *args, **kwargs):
        """Recalculer eligible_examen avant sauvegarde"""
        self.full_clean()
        # Recalculer l'éligibilité (sera mis à jour par le signal si nécessaire)
        super().save(*args, **kwargs)
    
    def calculer_eligible_examen(self):
        """
        Calcule si l'étudiant est éligible à l'examen basé sur les absences non justifiées.
        Retourne True si éligible, False sinon.
        """
        if self.exemption_40:
            return True
        
        from apps.absences.models import Absence
        
        # Calculer les absences non justifiées
        total_absence = Absence.objects.filter(
            id_inscription=self,
            statut='NON_JUSTIFIEE'
        ).aggregate(total=Sum('duree_absence'))['total'] or 0
        
        if self.id_cours.nombre_total_periodes == 0:
            return True
        
        # Utiliser le seuil du cours ou le seuil par défaut
        seuil = self.id_cours.get_seuil_absence()
        taux = (total_absence / self.id_cours.nombre_total_periodes) * 100
        
        return taux < seuil

    def __str__(self):
        return f"{self.id_etudiant.nom} {self.id_etudiant.prenom} -> {self.id_cours.nom_cours}"
