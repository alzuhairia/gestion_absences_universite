"""
Sérialiseurs d'utilisateur et d'étudiant pour l'API REST UniAbsences.

Ce module fournit deux sérialiseurs pour le modèle ``User`` :

- ``UserListSerializer`` — représentation en lecture seule utilisée par les
  points de terminaison de liste de l'administration ; expose les champs
  d'identité et de rôle plus un ``full_name`` calculé. Tous les champs sont
  en lecture seule.

- ``StudentSerializer`` — sérialiseur lecture/écriture portant sur les
  comptes étudiants ; utilisé par le ViewSet de gestion des étudiants pour
  les opérations de création et de mise à jour. Vérifie que ``niveau`` est
  l'un de 1, 2 ou 3.

Partie de l'API REST UniAbsences.
"""
from rest_framework import serializers

from apps.accounts.models import User


class UserListSerializer(serializers.ModelSerializer):
    """
    Vue plate en lecture seule d'un compte utilisateur.

    Utilisée par les points de terminaison de liste et de récupération côté
    administration pour afficher l'identité, le rôle et le statut d'activité
    sans autoriser les écritures via l'API.
    """

    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        """Configuration DRF : modèle ``User``, champs en lecture seule pour la liste admin."""

        model = User
        fields = [
            "id_utilisateur",
            "nom",
            "prenom",
            "email",
            "role",
            "actif",
            "niveau",
            "full_name",
            "date_creation",
        ]
        read_only_fields = fields


class StudentSerializer(serializers.ModelSerializer):
    """
    Sérialiseur lecture/écriture pour les comptes étudiants.

    Utilisé par StudentViewSet pour les opérations de création et de mise à
    jour. ``niveau`` est validé pour être exactement 1, 2 ou 3 ; toutes les
    autres contraintes (email unique, hachage du mot de passe) sont gérées
    par le modèle et UserManager.
    """

    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        """Configuration DRF : modèle ``User``, champs inscriptibles et règles ``extra_kwargs``."""

        model = User
        fields = [
            "id_utilisateur",
            "nom",
            "prenom",
            "email",
            "niveau",
            "actif",
            "full_name",
            "date_creation",
        ]
        read_only_fields = ["id_utilisateur", "date_creation", "full_name"]
        extra_kwargs = {
            "email": {"required": True},
            "nom": {"required": True},
            "prenom": {"required": True},
            "niveau": {"required": True},
        }

    def validate_niveau(self, value):
        """
        Vérifie que le niveau d'étude est l'une des trois valeurs acceptées.

        Le cursus universitaire s'étend sur exactement trois années, donc
        seuls les entiers 1, 2 et 3 sont des valeurs significatives pour ce
        champ. Tout autre entier (par exemple 0, 4) est une erreur de saisie
        et est rejeté avant que l'enregistrement n'atteigne la base de
        données.

        Parameters:
            value (int): L'entier ``niveau`` issu de la charge utile de la
                requête entrante.

        Returns:
            int: La valeur validée, inchangée.

        Raises:
            serializers.ValidationError: Si ``value`` n'est pas dans {1, 2, 3}.
        """
        # Seules trois années d'études existent dans le cursus universitaire
        if value not in (1, 2, 3):
            raise serializers.ValidationError("Le niveau doit être 1, 2 ou 3.")
        return value
