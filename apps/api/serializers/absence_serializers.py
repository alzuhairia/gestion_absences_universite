"""
Serializers d'absence pour l'API REST UniAbsences.

Ce module fournit deux serializers pour le modèle ``Absence`` :

- ``AbsenceListSerializer``  — serializer optimisé pour la lecture utilisé pour les
  actions ``list`` et ``retrieve``. Il ajoute plusieurs champs dénormalisés en
  lecture seule (nom de l'étudiant, code du cours, date/heure de la séance) afin
  que les consommateurs de l'API n'aient pas besoin d'effectuer de recherches
  supplémentaires.

- ``AbsenceWriteSerializer`` — serializer d'écriture utilisé pour les actions
  ``create``, ``update`` et ``partial_update``. Il applique deux règles métier :
    1. Une absence partielle (``PARTIEL``) doit fournir une valeur ``duree_absence``
       positive.
    2. La durée d'absence déclarée ne peut pas dépasser la durée totale de la
       séance liée.

Responsabilités :
  - Représenter les enregistrements d'absence dans les réponses REST avec des
    champs de contexte lisibles.
  - Valider les contraintes de type et de durée d'absence avant persistance en base.

Fait partie de l'API REST UniAbsences.
"""

from rest_framework import serializers

from apps.absences.models import Absence


class AbsenceListSerializer(serializers.ModelSerializer):
    """
    Serializer en lecture seule pour lister et récupérer les enregistrements d'absence.

    En plus des champs bruts du modèle, trois ensembles de champs dénormalisés
    sont inclus pour épargner aux consommateurs de l'API des requêtes
    supplémentaires :

    - ``etudiant_name`` — nom complet de l'étudiant absent, résolu via
      la relation d'inscription (``id_inscription → id_etudiant``).
    - ``cours_code``    — code du cours concerné, résolu via la relation
      d'inscription (``id_inscription → id_cours``).
    - ``date_seance``, ``heure_debut``, ``heure_fin`` — bornes de date et d'heure
      de la séance d'enseignement associée (``id_seance``).

    Tous les champs supplémentaires sont en ``read_only=True`` et sont remplis
    via des parcours ``source`` ; ils ne sont jamais inscriptibles.
    """

    # Identité de l'étudiant dénormalisée — évite un appel séparé /students/{id}/
    etudiant_name = serializers.CharField(
        source="id_inscription.id_etudiant.get_full_name", read_only=True
    )
    # Code de cours dénormalisé — fournit un contexte rapide sans recherche du cours
    cours_code = serializers.CharField(
        source="id_inscription.id_cours.code_cours", read_only=True
    )
    # Bornes de date et d'heure de la séance — exposées directement sur l'enregistrement d'absence
    date_seance = serializers.DateField(
        source="id_seance.date_seance", read_only=True
    )
    heure_debut = serializers.TimeField(
        source="id_seance.heure_debut", read_only=True
    )
    heure_fin = serializers.TimeField(
        source="id_seance.heure_fin", read_only=True
    )

    class Meta:
        """Configuration DRF : modèle ``Absence`` et champs dénormalisés exposés en lecture."""

        model = Absence
        fields = [
            "id_absence",
            "id_inscription",
            "etudiant_name",
            "cours_code",
            "id_seance",
            "date_seance",
            "heure_debut",
            "heure_fin",
            "type_absence",
            "duree_absence",
            "statut",
            "note_professeur",
            "encodee_par",
        ]


class AbsenceWriteSerializer(serializers.ModelSerializer):
    """
    Serializer d'écriture pour créer et mettre à jour les enregistrements d'absence.

    Champs acceptés :
      - ``id_inscription`` : l'inscription à laquelle cette absence appartient.
      - ``id_seance``      : la séance d'enseignement durant laquelle l'absence
                             a eu lieu.
      - ``type_absence``   : doit être ``ABSENT`` ou ``PARTIEL`` ; le type
                             ``JUSTIFIEE`` est défini automatiquement par le
                             workflow d'approbation des justifications et n'est
                             donc pas accepté en entrée.
      - ``duree_absence``  : durée en heures — requise et positive lorsque
                             ``type_absence`` est ``PARTIEL``.
      - ``note_professeur``: note libre optionnelle de l'enseignant.

    Validation des règles métier (``validate_type_absence`` + ``validate``) :
      1. ``type_absence`` doit être ``ABSENT`` ou ``PARTIEL``.
      2. Pour une absence partielle, ``duree_absence`` doit être fournie et > 0.
      3. ``duree_absence`` ne peut pas dépasser la durée de la séance liée
         (calculée via ``Seance.duree_heures()``).
    """

    class Meta:
        """Configuration DRF : modèle ``Absence`` et champs inscriptibles via l'API."""

        model = Absence
        fields = [
            "id_inscription",
            "id_seance",
            "type_absence",
            "duree_absence",
            "note_professeur",
        ]

    def validate_type_absence(self, value):
        """
        Valide que le type d'absence est l'une des deux valeurs d'entrée acceptées.

        Seuls ``ABSENT`` et ``PARTIEL`` sont autorisés au moment de la création/mise à jour.
        ``JUSTIFIEE`` est un état géré par le système, défini par le processus
        d'approbation de justification et ne doit pas être soumis directement par
        les consommateurs de l'API.

        Args:
            value: La valeur brute de ``type_absence`` issue du payload entrant.

        Retourne:
            La valeur validée, inchangée.

        Lève:
            serializers.ValidationError: Si ``value`` n'est pas dans l'ensemble
                autorisé.
        """
        allowed = (Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL)
        if value not in allowed:
            raise serializers.ValidationError(
                f"Type invalide. Valeurs autorisées : {', '.join(allowed)}"
            )
        return value

    def validate(self, data):
        """
        Effectue la validation inter-champs de ``type_absence`` et ``duree_absence``.

        Deux règles sont appliquées :

        1. Si ``type_absence`` est ``PARTIEL``, ``duree_absence`` doit être
           présente et strictement positive. Une absence partielle avec zéro ou
           aucune durée n'a pas de sens.

        2. Si une séance (``id_seance``) et une durée positive sont toutes deux
           présentes, la durée ne doit pas dépasser la longueur totale de la séance
           (obtenue via ``Seance.duree_heures()``). Cela évite les erreurs de
           saisie où plus d'heures sont enregistrées que la séance n'a réellement
           duré.

        Args:
            data: Le dictionnaire des valeurs de champ validées avant les
                  vérifications inter-champs.

        Retourne:
            Le dictionnaire de données validé, inchangé si toutes les règles passent.

        Lève:
            serializers.ValidationError: Si l'une des deux règles est
                violée.
        """
        type_absence = data.get("type_absence")
        duree = data.get("duree_absence")

        # Règle 1 : les absences partielles nécessitent une durée positive
        if type_absence == Absence.TypeAbsence.PARTIEL and (not duree or duree <= 0):
            raise serializers.ValidationError(
                {"duree_absence": "La durée est obligatoire pour une absence partielle."}
            )

        # Règle 2 : la durée d'absence ne peut pas dépasser la longueur de la séance
        seance = data.get("id_seance")
        if seance and duree is not None and duree > 0:
            duree_seance = seance.duree_heures() if hasattr(seance, "duree_heures") else None
            if duree_seance and float(duree) > duree_seance:
                raise serializers.ValidationError(
                    {"duree_absence": f"La durée ({duree}h) ne peut pas dépasser la durée de la séance ({duree_seance}h)."}
                )

        return data
