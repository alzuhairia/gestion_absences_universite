"""
Sérialiseurs d'inscription pour l'API REST UniAbsences.

Ce module fournit deux sérialiseurs pour la ressource ``Inscription`` :

- ``InscriptionListSerializer`` — représentation plate optimisée en lecture
  utilisée par les points de terminaison de liste et de récupération ; résout
  les noms liés à partir des identifiants de clés étrangères afin que les
  appelants reçoivent des libellés lisibles d'étudiant/cours/année à côté des
  identifiants bruts.

- ``InscriptionWriteSerializer`` — sérialiseur d'écriture minimal utilisé par
  les points de terminaison de création et de mise à jour ; n'accepte que les
  quatre champs modifiables et vérifie que l'utilisateur sélectionné est un
  étudiant (rôle == ETUDIANT).

Partie de l'API REST UniAbsences.
"""
from rest_framework import serializers

from apps.accounts.models import User
from apps.enrollments.models import Inscription


class InscriptionListSerializer(serializers.ModelSerializer):
    """
    Vue plate en lecture seule d'un enregistrement d'inscription.

    Expose les champs de noms résolus à côté des identifiants bruts de clés
    étrangères afin que les consommateurs de l'API puissent afficher des
    libellés significatifs sans requêtes supplémentaires.
    """

    # Nom complet de l'étudiant résolu — évite une requête séparée à /students/{id}/
    etudiant_name = serializers.CharField(
        source="id_etudiant.get_full_name", read_only=True
    )
    # Code et nom du cours résolus — fournit le contexte sans requête sur le cours
    cours_code = serializers.CharField(
        source="id_cours.code_cours", read_only=True
    )
    cours_name = serializers.CharField(
        source="id_cours.nom_cours", read_only=True
    )
    # Libellé de l'année académique résolu (par exemple "2024-2025")
    annee = serializers.CharField(source="id_annee.libelle", read_only=True)

    class Meta:
        """Configuration DRF : modèle ``Inscription`` et champs dénormalisés exposés en lecture."""

        model = Inscription
        fields = [
            "id_inscription",
            "id_etudiant",
            "etudiant_name",
            "id_cours",
            "cours_code",
            "cours_name",
            "id_annee",
            "annee",
            "type_inscription",
            "eligible_examen",
            "status",
            "exemption_40",
            "motif_exemption",
        ]


class InscriptionWriteSerializer(serializers.ModelSerializer):
    """
    Sérialiseur d'écriture pour créer et mettre à jour les enregistrements
    d'inscription.

    Accepte les quatre identifiants principaux et rejette l'inscription de
    tout utilisateur dont le rôle n'est pas ETUDIANT, empêchant l'inscription
    accidentelle de comptes du personnel.
    """

    class Meta:
        """Configuration DRF : modèle ``Inscription`` et champs inscriptibles via l'API."""

        model = Inscription
        fields = [
            "id_etudiant",
            "id_cours",
            "id_annee",
            "type_inscription",
        ]

    def validate_id_etudiant(self, value):
        """
        Vérifie que l'utilisateur sélectionné est un étudiant.

        Empêche l'inscription accidentelle de comptes du personnel
        (professeurs, secrétaires, administrateurs) en imposant que
        l'utilisateur fourni ait le rôle ETUDIANT avant que l'enregistrement
        ne soit sauvegardé.

        Parameters:
            value (User): L'instance ``User`` résolue à partir de la clé
                primaire entrante.

        Returns:
            User: L'instance d'utilisateur validée, inchangée.

        Raises:
            serializers.ValidationError: Si le rôle de l'utilisateur n'est pas
                ``User.Role.ETUDIANT``.
        """
        # Rejeter les utilisateurs non étudiants — seuls les comptes ETUDIANT peuvent être inscrits
        if value.role != User.Role.ETUDIANT:
            raise serializers.ValidationError("L'utilisateur doit avoir le rôle ETUDIANT.")
        return value
