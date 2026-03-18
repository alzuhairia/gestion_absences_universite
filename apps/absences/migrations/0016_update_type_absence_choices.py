"""
Migration: Update TypeAbsence choices.

Schema change:
- Adds new choices ABSENT, PARTIEL to type_absence field
- Changes default from SEANCE to ABSENT

Data migration:
- Converts SEANCE → ABSENT
- Converts JOURNEE → ABSENT (with duree_absence = seance duration)
- Converts HEURE → PARTIEL
- Converts RETARD → PARTIEL (if any from intermediate state)

Design note:
- Pas de record Absence = étudiant présent (absence inexistante = présence)
- ABSENT = absence complète (durée = durée séance)
- PARTIEL = toute absence non complète (retard, départ anticipé, etc.)
"""

from django.db import migrations, models


def convert_legacy_types(apps, schema_editor):
    """Convert legacy absence types to the new ABSENT/PARTIEL types."""
    Absence = apps.get_model("absences", "Absence")
    from datetime import datetime, timedelta

    # SEANCE → ABSENT (duree_absence already correct — equals seance duration)
    Absence.objects.filter(type_absence="SEANCE").update(type_absence="ABSENT")

    # JOURNEE → ABSENT (set duree_absence = seance duration if it was 8h placeholder)
    for absence in Absence.objects.filter(type_absence="JOURNEE").select_related("id_seance"):
        seance = absence.id_seance
        if seance and seance.heure_debut and seance.heure_fin:
            date_ref = datetime(2000, 1, 1)
            debut = datetime.combine(date_ref, seance.heure_debut)
            fin = datetime.combine(date_ref, seance.heure_fin)
            if fin < debut:
                fin += timedelta(days=1)
            duree = round((fin - debut).total_seconds() / 3600.0, 2)
            absence.duree_absence = duree
        absence.type_absence = "ABSENT"
        absence.save(update_fields=["type_absence", "duree_absence"])

    # HEURE → PARTIEL (duree_absence already has the partial duration)
    Absence.objects.filter(type_absence="HEURE").update(type_absence="PARTIEL")

    # RETARD → PARTIEL (catch any intermediate migration state)
    Absence.objects.filter(type_absence="RETARD").update(type_absence="PARTIEL")


def reverse_types(apps, schema_editor):
    """Reverse: convert new types back to legacy types."""
    Absence = apps.get_model("absences", "Absence")
    Absence.objects.filter(type_absence="ABSENT").update(type_absence="SEANCE")
    Absence.objects.filter(type_absence="PARTIEL").update(type_absence="HEURE")


class Migration(migrations.Migration):

    dependencies = [
        ("absences", "0015_qr_gps_antifraud"),
    ]

    operations = [
        # Step 1: Alter the field to accept both old and new values during migration
        migrations.AlterField(
            model_name="absence",
            name="type_absence",
            field=models.CharField(
                choices=[
                    ("ABSENT", "Absent"),
                    ("PARTIEL", "Absence partielle"),
                    ("HEURE", "Heure (legacy)"),
                    ("SEANCE", "Séance (legacy)"),
                    ("JOURNEE", "Journée (legacy)"),
                    ("RETARD", "Retard (legacy)"),
                ],
                db_index=True,
                default="ABSENT",
                max_length=20,
                verbose_name="Type d'absence",
            ),
        ),
        # Step 2: Convert data
        migrations.RunPython(convert_legacy_types, reverse_types),
    ]
