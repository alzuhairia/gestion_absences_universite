"""
Sérialiseurs des cours et des séances pour l'API REST UniAbsences.

Ce module définit quatre sérialiseurs qui couvrent la lecture et l'écriture des
données pour les modèles ``Cours`` et ``Seance`` (séance d'enseignement) :

- ``SeanceSerializer``      — sérialiseur lecture/écriture pour les séances
  d'enseignement. Ajoute les champs pratiques ``cours_code`` et ``duree``.

- ``CoursListSerializer``   — sérialiseur de lecture optimisé pour les réponses
  de liste. Dénormalise le nom du département, le nom du professeur, le libellé
  de l'année académique et le seuil d'absence effectif afin que les consommateurs
  de listes évitent des requêtes supplémentaires.

- ``CoursDetailSerializer`` — étend ``CoursListSerializer`` avec la liste
  complète des séances associées et des cours prérequis. Utilisé uniquement
  pour les actions ``retrieve`` où les données supplémentaires sont
  explicitement demandées.

- ``CoursWriteSerializer``  — sérialiseur d'écriture minimal pour les actions
  ``create``, ``update`` et ``partial_update``. Vérifie que le champ ``niveau``
  est l'un des trois niveaux d'étude acceptés (1, 2 ou 3).

Responsabilités :
  - Exposer les métadonnées des cours aux consommateurs de l'API dans un format
    adapté au frontend.
  - Empêcher les valeurs de niveau d'étude invalides d'atteindre la base de
    données.

Partie de l'API REST UniAbsences — module Cours.
"""

from rest_framework import serializers

from apps.academic_sessions.models import Seance
from apps.academics.models import Cours


class SeanceSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour le modèle ``Seance`` (séance d'enseignement).

    Champs pratiques en lecture seule ajoutés en plus des champs bruts du
    modèle :

    - ``cours_code`` — le code du cours parent, résolu via la clé étrangère
      ``id_cours``. Évite une requête séparée sur le cours.
    - ``duree``      — la durée de la séance en heures décimales, calculée en
      appelant ``Seance.duree_heures()``.

    Les champs ``id_seance``, ``validated``, ``cours_code`` et ``duree`` sont
    en lecture seule ; tous les autres champs peuvent être définis à la
    création ou à la mise à jour.
    """

    # Code de cours dénormalisé — lecture seule calculée à partir de la FK
    cours_code = serializers.CharField(
        source="id_cours.code_cours", read_only=True
    )
    # Durée en heures — calculée par la méthode du modèle, jamais stockée directement
    duree = serializers.FloatField(source="duree_heures", read_only=True)

    class Meta:
        """Configuration DRF : modèle ``Seance``, champs exposés et champs en lecture seule."""

        model = Seance
        fields = [
            "id_seance",
            "date_seance",
            "heure_debut",
            "heure_fin",
            "id_cours",
            "cours_code",
            "id_annee",
            "validated",
            "duree",
        ]
        read_only_fields = [
            "id_seance",    # Clé primaire générée automatiquement
            "validated",    # Définie par le workflow de validation, pas par l'entrée API
            "cours_code",   # Calculé à partir de la FK
            "duree",        # Calculée par la méthode du modèle
        ]


class CoursListSerializer(serializers.ModelSerializer):
    """
    Sérialiseur optimisé en lecture pour lister les enregistrements de cours.

    Champs dénormalisés ajoutés pour éviter les requêtes secondaires :

    - ``departement_name`` — nom lisible du département depuis
      ``id_departement.nom_departement``.
    - ``professeur_name``  — nom complet du professeur assigné, ou ``None``
      lorsqu'aucun professeur n'est encore assigné.
    - ``annee``            — libellé de l'année académique depuis
      ``id_annee.libelle``.
    - ``seuil_effectif``   — seuil d'absence *effectif* pour ce cours, calculé
      par ``Cours.get_seuil_absence()`` (qui utilise la valeur par défaut du
      système lorsqu'aucun seuil spécifique au cours n'est défini).

    Tous les champs dénormalisés sont ``read_only=True`` et ne sont jamais
    acceptés en entrée.
    """

    # Nom du département résolu — évite un appel séparé à /departments/
    departement_name = serializers.CharField(
        source="id_departement.nom_departement", read_only=True
    )
    # Nom complet du professeur résolu — None si le cours n'a pas de professeur assigné
    professeur_name = serializers.CharField(
        source="professeur.get_full_name", read_only=True, default=None
    )
    # Libellé de l'année académique (par exemple "2024-2025")
    annee = serializers.CharField(source="id_annee.libelle", read_only=True)
    # Seuil effectif — utilise la surcharge au niveau du cours ou la valeur par défaut du système
    seuil_effectif = serializers.IntegerField(
        source="get_seuil_absence", read_only=True
    )

    class Meta:
        """Configuration DRF : modèle ``Cours`` et champs dénormalisés exposés en lecture."""

        model = Cours
        fields = [
            "id_cours",
            "code_cours",
            "nom_cours",
            "nombre_total_periodes",
            "seuil_absence",        # Valeur brute stockée (peut être None — signifie "utiliser la valeur par défaut")
            "seuil_effectif",       # Valeur effective résolue (toujours un entier)
            "id_departement",
            "departement_name",
            "professeur",
            "professeur_name",
            "id_annee",
            "annee",
            "niveau",
            "actif",
        ]


class CoursDetailSerializer(CoursListSerializer):
    """
    Sérialiseur étendu pour l'action ``retrieve``.

    Hérite de tous les champs de ``CoursListSerializer`` et ajoute :

    - ``seances``      — toutes les séances d'enseignement associées à ce cours,
      sérialisées comme une liste imbriquée d'objets ``SeanceSerializer``.
    - ``prerequisites`` — cours prérequis, sérialisés comme une liste imbriquée
      d'objets ``CoursListSerializer`` (auto-référentiels, à un niveau de
      profondeur).

    Les deux champs imbriqués sont en lecture seule ; les prérequis et les
    séances sont gérés via leurs propres points de terminaison dédiés.
    """

    # Liste de séances imbriquée — pré-chargée par CoursViewSet.get_queryset()
    seances = SeanceSerializer(many=True, read_only=True)
    # Prérequis auto-référentiels — utilise le sérialiseur de liste pour éviter la récursion
    prerequisites = CoursListSerializer(many=True, read_only=True)

    class Meta(CoursListSerializer.Meta):
        """Hérite de la configuration ``CoursListSerializer`` et ajoute les relations imbriquées."""

        # Ajoute les deux champs imbriqués à la liste de champs héritée
        fields = CoursListSerializer.Meta.fields + ["seances", "prerequisites"]


class CoursWriteSerializer(serializers.ModelSerializer):
    """
    Sérialiseur d'écriture pour créer et mettre à jour les enregistrements de
    cours.

    Les champs d'entrée acceptés reflètent les colonnes inscriptibles du modèle
    ``Cours``. Le champ ``actif`` contrôle la suppression logique ; le définir
    à ``False`` est préférable à la suppression définitive de cours possédant
    des enregistrements associés.

    Validation :
        ``validate_niveau`` — rejette tout niveau d'étude en dehors de
        l'ensemble accepté {1, 2, 3}. L'université n'a que trois années
        d'études, donc toute autre valeur est une erreur de saisie.
    """

    class Meta:
        """Configuration DRF : champs inscriptibles du modèle ``Cours`` exposés en écriture."""

        model = Cours
        fields = [
            "code_cours",
            "nom_cours",
            "nombre_total_periodes",
            "seuil_absence",       # Surcharge optionnelle ; None signifie utiliser la valeur par défaut du système
            "id_departement",
            "professeur",
            "id_annee",
            "niveau",
            "prerequisites",       # ManyToMany — accepte une liste de PKs de Cours
            "actif",
        ]

    def validate_niveau(self, value: int) -> int:
        """
        Vérifie que le niveau d'étude est l'une des trois valeurs acceptées.

        Le cursus universitaire s'étend sur exactement trois années, donc
        seuls les entiers 1, 2 et 3 sont des valeurs significatives pour ce
        champ.

        Args:
            value: L'entier ``niveau`` issu de la charge utile de la requête
                entrante.

        Returns:
            La valeur validée, inchangée.

        Raises:
            serializers.ValidationError: Si ``value`` n'est pas dans {1, 2, 3}.
        """
        if value not in (1, 2, 3):
            raise serializers.ValidationError("Le niveau doit être 1, 2 ou 3.")
        return value
