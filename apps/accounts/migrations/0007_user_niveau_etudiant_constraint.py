from django.db import migrations, models


def set_default_niveau_for_students(apps, schema_editor):
    """
    Assigne niveau=1 à tous les étudiants qui n'ont pas encore de niveau défini.
    Nécessaire avant d'ajouter la contrainte etudiant_doit_avoir_niveau.
    """
    User = apps.get_model("accounts", "User")
    User.objects.filter(role="ETUDIANT", niveau__isnull=True).update(niveau=1)


class Migration(migrations.Migration):
    """
    FIX VERT #16 — Contrainte DB : tout utilisateur ETUDIANT doit avoir un niveau.
    Garantit l'intégrité des données au niveau base de données (pas seulement applicatif).

    Note : les étudiants existants sans niveau reçoivent niveau=1 par défaut avant
    l'ajout de la contrainte.
    """

    dependencies = [
        ("accounts", "0006_user_nom_prenom_idx_concurrently"),
    ]

    operations = [
        # Corriger les données existantes avant d'ajouter la contrainte
        migrations.RunPython(
            set_default_niveau_for_students,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=(~models.Q(role="ETUDIANT") | models.Q(niveau__isnull=False)),
                name="etudiant_doit_avoir_niveau",
            ),
        ),
    ]
