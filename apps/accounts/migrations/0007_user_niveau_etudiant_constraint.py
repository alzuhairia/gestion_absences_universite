from django.db import migrations, models


class Migration(migrations.Migration):
    """
    FIX VERT #16 — Contrainte DB : tout utilisateur ETUDIANT doit avoir un niveau.
    Garantit l'intégrité des données au niveau base de données (pas seulement applicatif).
    """

    dependencies = [
        ("accounts", "0006_user_nom_prenom_idx_concurrently"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=(~models.Q(role="ETUDIANT") | models.Q(niveau__isnull=False)),
                name="etudiant_doit_avoir_niveau",
            ),
        ),
    ]
