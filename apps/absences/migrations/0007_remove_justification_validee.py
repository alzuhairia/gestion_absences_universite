from django.db import migrations


class Migration(migrations.Migration):
    """
    FIX VERT #17 — Suppression du champ deprecated Justification.validee.
    Le champ state (EN_ATTENTE / ACCEPTEE / REFUSEE) est désormais la seule source de vérité.
    Toutes les vues et l'admin ont été mis à jour pour ne plus référencer validee.

    Note : le trigger PostgreSQL trigger_verifier_seuil_justification dépend de la
    colonne validee — il doit être supprimé avant le RemoveField.
    """

    dependencies = [
        ("absences", "0006_absence_absence_duree_absence_non_negative"),
    ]

    operations = [
        # Suppression du trigger PostgreSQL qui dépend de la colonne validee
        migrations.RunSQL(
            sql="DROP TRIGGER IF EXISTS trigger_verifier_seuil_justification ON justification;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RemoveField(
            model_name="justification",
            name="validee",
        ),
    ]
