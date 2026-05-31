"""
Configuration de l'administration Django pour l'application audits d'UniAbsences.

Enregistre ``LogAudit`` auprès du site d'administration Django dans une
configuration en lecture seule et protégée contre la suppression, afin
de préserver l'intégrité de la piste d'audit. Tous les champs sont
marqués comme ``readonly_fields`` et ``has_delete_permission`` est
surchargé pour toujours retourner ``False``.

Fait partie du système d'audit UniAbsences.
"""

from django.contrib import admin

from .models import LogAudit


@admin.register(LogAudit)
class LogAuditAdmin(admin.ModelAdmin):
    """
    Interface d'administration pour le modèle LogAudit.

    Garantit l'immuabilité des enregistrements d'audit :

    - Tous les champs sont en lecture seule — aucune modification n'est
      possible via l'administration.
    - La suppression est désactivée au niveau de l'admin via
      ``has_delete_permission``.
    - ``list_select_related`` évite les requêtes N+1 lors de l'affichage
      de la colonne utilisateur sur des ensembles de résultats paginés.
    - ``search_fields`` permet une recherche textuelle par description
      d'action ou par nom/prénom de l'utilisateur ayant agi.
    """

    # Colonnes visibles dans la liste de modification
    list_display = ("id_utilisateur", "action", "date_action", "adresse_ip")
    # Résout la FK utilisateur en une seule jointure plutôt que par requêtes individuelles
    list_select_related = ("id_utilisateur",)
    # Filtres latéraux pour restreindre par date ou acteur
    list_filter = ("date_action", "id_utilisateur")
    # Recherche libre sur le texte de l'action et les champs de nom utilisateur
    search_fields = ("action", "id_utilisateur__nom", "id_utilisateur__prenom")
    # Tous les champs sont en lecture seule — les journaux d'audit ne doivent jamais être modifiés
    readonly_fields = ("id_utilisateur", "action", "date_action", "adresse_ip")

    def has_delete_permission(self, request, obj=None):
        """
        Empêche la suppression des entrées du journal d'audit via l'interface d'administration.

        Le retour inconditionnel de ``False`` supprime l'action « Supprimer »
        de la liste de modification ainsi que le bouton « Supprimer » du
        formulaire de détail, garantissant que la piste d'audit ne peut pas
        être altérée via l'administration.

        Paramètres
        ----------
        request : HttpRequest
            La requête d'administration courante.
        obj : LogAudit or None
            L'entrée de journal spécifique consultée, ou ``None`` pour les
            vérifications de permission au niveau liste.

        Retourne
        --------
        bool
            Toujours ``False``.
        """
        return False
