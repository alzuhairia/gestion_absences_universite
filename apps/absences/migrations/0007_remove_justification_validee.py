from django.db import migrations


class Migration(migrations.Migration):
    """
    FIX VERT #17 — Suppression du champ deprecated Justification.validee.
    Le champ state (EN_ATTENTE / ACCEPTEE / REFUSEE) est désormais la seule source de vérité.
    Toutes les vues et l'admin ont été mis à jour pour ne plus référencer validee.
    """

    dependencies = [
        ("absences", "0006_absence_absence_duree_absence_non_negative"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="justification",
            name="validee",
        ),
    ]
