"""
Commande de gestion : migrate_justification_documents
— apps/absences/management/commands/migrate_justification_documents.py

Fait partie du système universitaire de gestion des présences UniAbsences.

Cette commande de migration de données ponctuelle copie les BLOBs de
documents justificatifs qui étaient stockés dans une colonne binaire de
base de données vers le stockage de fichiers backed par ``FileField`` de
Django (typiquement le système de fichiers local ou un backend objet).

Elle est conçue pour être idempotente : les lignes dont la colonne cible
est déjà renseignée sont ignorées, donc la commande peut être ré-exécutée
en toute sécurité après un échec partiel.

Fenêtre d'exécution prévue :
    Exécutez cette commande APRÈS l'application de la migration 0003 (qui
    ajoute la colonne FileField cible) et AVANT l'application de la
    migration 0004 (qui supprime l'ancienne colonne BLOB). La commande
    vérifie que les deux colonnes existent avant de traiter une seule ligne
    et abandonne avec un message d'erreur clair sinon.

Utilisation ::

    # Migre tous les enregistrements dans le modèle Justification par défaut, 200 à la fois :
    python manage.py migrate_justification_documents

    # Prévisualise ce qui serait migré sans rien écrire :
    python manage.py migrate_justification_documents --dry-run

    # Utilise un lot plus petit, en partant d'une clé primaire précise :
    python manage.py migrate_justification_documents --batch-size 50 --start-id 1000

    # S'arrête après avoir migré 500 enregistrements :
    python manage.py migrate_justification_documents --limit 500

    # Cible un autre modèle ou une autre disposition de colonnes :
    python manage.py migrate_justification_documents \\
        --model absences.Justification \\
        --source-column document \\
        --target-column document_file
"""
import re
from typing import cast

from django.apps import apps as django_apps
from django.core.exceptions import FieldDoesNotExist
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Field, Model


class Command(BaseCommand):
    """
    Commande de gestion Django qui migre par lots les BLOBs de documents
    justificatifs vers le stockage ``FileField``.

    La migration est réalisée par lots configurables en utilisant la
    pagination par clé (``WHERE pk > last_id ORDER BY pk LIMIT batch_size``)
    pour éviter de charger toute la table en mémoire. Chaque ligne est
    traitée atomiquement : le fichier est écrit dans le stockage et la
    colonne de la base est mise à jour dans le même bloc
    ``transaction.atomic()`` afin qu'un échec partiel laisse la ligne dans
    un état cohérent (source renseignée, cible vide) qui sera retenté lors
    de la prochaine exécution.

    Attributs :
        help (str) : description courte affichée par
            ``manage.py help migrate_justification_documents``.
    """

    help = "Migre par lots les BLOBs de documents justificatifs vers le stockage FileField."

    def add_arguments(self, parser):
        """
        Déclare tous les arguments en ligne de commande.

        Args :
            parser (argparse.ArgumentParser) : le parser d'arguments fourni
                par le framework de gestion de Django.
        """
        parser.add_argument("--batch-size", type=int, default=200,
                            help="Nombre de lignes à traiter par requête à la base (par défaut : 200).")
        parser.add_argument("--start-id", type=int, default=0,
                            help="Valeur de clé primaire à partir de laquelle commencer ; les lignes avec pk <= start-id sont ignorées.")
        parser.add_argument("--limit", type=int, default=0,
                            help="S'arrête après avoir migré N lignes (0 = pas de limite).")
        parser.add_argument("--model", default="absences.Justification",
                            help="app_label.ModelName Django du modèle à migrer (par défaut : absences.Justification).")
        parser.add_argument("--table", default="",
                            help="Surcharge le nom de la table en base (par défaut, le db_table du modèle).")
        parser.add_argument("--source-column", default="document",
                            help="Nom du champ du modèle ou nom brut de la colonne contenant les données BLOB.")
        parser.add_argument("--target-column", default="document_file",
                            help="Nom du champ du modèle ou nom brut de la colonne pour le chemin FileField.")
        parser.add_argument("--pk-column", default="",
                            help="Surcharge le nom de la colonne clé primaire (par défaut, la colonne pk du modèle).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Affiche ce qui serait migré sans écrire de fichier ni mettre à jour la base.")

    # ------------------------------------------------------------------
    # Helpers privés
    # ------------------------------------------------------------------

    def _validate_identifier(self, name, label):
        """
        Vérifie qu'un identifiant de table ou de colonne contient uniquement des caractères sûrs.

        Seuls les identifiants correspondant à ``^[A-Za-z_][A-Za-z0-9_]*$``
        sont acceptés. Cela empêche l'injection SQL via les requêtes SQL
        brutes utilisées pour la pagination par clé, où la paramétrisation
        de Django ne peut pas protéger les identifiants.

        Args :
            name (str | None) : la chaîne d'identifiant à valider.
            label (str) : libellé lisible utilisé dans le message d'erreur.

        Lève :
            ValueError : si ``name`` ne correspond pas au motif d'identifiant sûr.
        """
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
            raise ValueError(f"{label} invalide : {name}")

    def _get_model(self, model_label):
        """
        Résout une chaîne Django ``app_label.ModelName`` en classe de modèle.

        Args :
            model_label (str) : libellé complet du modèle
                (ex. ``"absences.Justification"``).

        Retour :
            type[Model] : la classe de modèle Django résolue.

        Lève :
            ValueError : si le libellé ne peut pas être résolu (app non
                installée ou modèle inexistant).
        """
        try:
            return django_apps.get_model(model_label)
        except Exception as exc:
            raise ValueError(f"Libellé de modèle invalide : {model_label}") from exc

    def _resolve_column(self, model: type[Model], name: str, label: str) -> str:
        """
        Résout un nom de champ de modèle en son nom de colonne sous-jacent dans la base.

        Si ``name`` correspond à un champ de modèle, l'attribut ``column``
        du champ est retourné (qui peut différer du nom du champ lorsque
        ``db_column`` est défini). Si le champ n'est pas trouvé, ``name``
        est retourné tel quel, permettant aux appelants de passer
        directement des noms de colonnes bruts.

        Args :
            model (type[Model]) : classe de modèle Django à inspecter.
            name (str) : nom de champ ou nom brut de colonne à résoudre.
            label (str) : libellé lisible utilisé dans le message d'erreur
                lorsque ``name`` est vide.

        Retour :
            str : le nom de colonne en base résolu.

        Lève :
            ValueError : si ``name`` est une chaîne vide.
        """
        if not name:
            raise ValueError(f"{label} manquant")
        try:
            field = cast(Field, model._meta.get_field(name))
        except FieldDoesNotExist:
            # Traite comme un nom de colonne brut et laisse la validation SQL détecter les problèmes.
            return name
        return field.column

    def _assert_column_exists(self, table, column):
        """
        Vérifie qu'une colonne existe sur la table donnée de la base de données.

        Interroge ``information_schema.columns`` pour confirmer que la
        colonne est présente avant le démarrage de la boucle par lots. Cela
        fournit un message d'erreur précoce et exploitable au lieu d'une
        erreur SQL cryptique en plein milieu de la migration.

        Args :
            table (str) : nom de table en base.
            column (str) : nom de colonne à vérifier.

        Lève :
            ValueError : si la colonne n'est pas trouvée sur la table, avec
                un indice pointant vers la migration qui doit être appliquée
                au préalable.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
                """,
                [table, column],
            )
            if cursor.fetchone() is None:
                raise ValueError(
                    f"Colonne '{column}' introuvable sur la table '{table}'. "
                    "Exécutez d'abord la migration 0003 puis cette commande avant la 0004."
                )

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        """
        Exécute la migration BLOB-vers-fichier par lots.

        Étapes :
          1. Résoudre et valider toutes les entrées (modèle, table, noms de colonnes).
          2. Confirmer que les colonnes source et cible existent en base.
          3. Itérer par lots en utilisant la pagination par clé :
               a. Récupérer jusqu'à ``batch_size`` lignes dont la colonne
                  source est renseignée et la colonne cible vide.
               b. Pour chaque ligne, enregistrer les octets BLOB dans
                  ``default_storage``.
               c. Mettre à jour la colonne cible avec le chemin du fichier
                  enregistré dans une transaction atomique.
          4. S'arrêter quand il n'y a plus de ligne ou que ``--limit`` est atteint.

        Args :
            *args : arguments positionnels (inutilisés ; requis par la classe de base).
            **options (dict) : options de commande analysées. Voir
                ``add_arguments`` pour la liste complète des clés acceptées.

        Effets de bord :
            - Écrit des fichiers vers ``default_storage``.
            - Met à jour la colonne cible pour chaque ligne migrée.
            - Affiche la progression et un récapitulatif final sur ``self.stdout``.
        """
        batch_size = options["batch_size"]
        start_id = options["start_id"]
        limit = options["limit"]
        model_label = options["model"]
        table = options["table"]
        source_col = options["source_column"]
        target_col = options["target_column"]
        pk_col = options["pk_column"]
        dry_run = options["dry_run"]

        model = self._get_model(model_label)

        # Par défaut, utilise le db_table du modèle si la table n'est pas surchargée.
        if not table:
            table = model._meta.db_table

        # Par défaut, utilise la colonne du champ clé primaire du modèle.
        if not pk_col:
            pk_field = model._meta.pk
            assert pk_field is not None
            pk_col = pk_field.column

        # Résout les noms de champs en noms de colonnes en base sous-jacents.
        source_col = self._resolve_column(model, source_col, "colonne/champ source")
        target_col = self._resolve_column(model, target_col, "colonne/champ cible")

        # Valide que tous les identifiants sont sûrs avant de les intégrer dans le SQL.
        self._validate_identifier(table, "table")
        self._validate_identifier(source_col, "colonne source")
        self._validate_identifier(target_col, "colonne cible")
        self._validate_identifier(pk_col, "colonne pk")

        # Vérification préalable : confirme que les deux colonnes existent dans le schéma.
        self._assert_column_exists(table, source_col)
        self._assert_column_exists(table, target_col)

        total_migrated = 0
        last_id = start_id

        self.stdout.write(
            f"Démarrage de la migration par lots : model={model_label}, table={table}, source={source_col}, "
            f"target={target_col}, pk={pk_col}, batch_size={batch_size}, "
            f"start_id={start_id}, limit={limit}, dry_run={dry_run}"
        )

        while True:
            # Pagination par clé : récupère le lot suivant de lignes dont la colonne
            # BLOB est renseignée et dont la colonne FileField n'a pas encore été remplie.
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {pk_col}, {source_col}
                    FROM {table}
                    WHERE {pk_col} > %s
                      AND {source_col} IS NOT NULL
                      AND ({target_col} IS NULL OR {target_col} = '')
                    ORDER BY {pk_col}
                    LIMIT %s
                    """,  # nosec B608 — les identifiants sont validés ci-dessus
                    [last_id, batch_size],
                )
                rows = cursor.fetchall()

            # Plus de lignes à traiter — la migration est complète.
            if not rows:
                break

            for pk_value, data in rows:
                last_id = pk_value

                if data is None:
                    continue

                # Gère les objets memoryview retournés par certains backends de base (ex. psycopg2).
                if hasattr(data, "tobytes"):
                    data = data.tobytes()

                if not data:
                    continue

                # Construit un nom de fichier déterministe basé sur la clé primaire de la ligne.
                filename = f"justifications/justification_{pk_value}.bin"
                saved_name = filename

                if not dry_run:
                    # Enregistre les octets BLOB dans le backend de stockage de fichiers configuré.
                    saved_name = default_storage.save(filename, ContentFile(data))

                if not dry_run:
                    # Met à jour la colonne FileField atomiquement avec le chemin sauvegardé.
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(
                                f"""
                                UPDATE {table}
                                SET {target_col} = %s
                                WHERE {pk_col} = %s
                                """,  # nosec B608 — les identifiants sont validés ci-dessus
                                [saved_name, pk_value],
                            )

                total_migrated += 1

                # Respecte le drapeau --limit s'il est défini.
                if limit and total_migrated >= limit:
                    self.stdout.write("Limite atteinte, arrêt.")
                    return

            self.stdout.write(f"Migrés jusqu'à présent : {total_migrated}")

        self.stdout.write(f"Terminé. Total migré : {total_migrated}")
