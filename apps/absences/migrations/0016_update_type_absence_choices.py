"""
Migration : mise à jour des choix de TypeAbsence.

Changement de schéma :
- Ajoute les nouveaux choix ABSENT, PARTIEL au champ type_absence
- Change la valeur par défaut de SEANCE à ABSENT

Migration de données :
- Convertit SEANCE → ABSENT
- Convertit JOURNEE → ABSENT (avec duree_absence = durée de la séance)
- Convertit HEURE → PARTIEL
- Convertit RETARD → PARTIEL (si présent depuis un état intermédiaire)

Note de conception :
- Pas de record Absence = étudiant présent (absence inexistante = présence)
- ABSENT = absence complète (durée = durée séance)
- PARTIEL = toute absence non complète (retard, départ anticipé, etc.)
"""

from django.db import migrations, models


def convert_legacy_types(apps, schema_editor):
    """Convertit les anciens types d'absence vers les nouveaux types ABSENT/PARTIEL."""
    Absence = apps.get_model("absences", "Absence")
    from datetime import datetime, timedelta

    # SEANCE → ABSENT (duree_absence déjà correcte — égale à la durée de la séance)
    Absence.objects.filter(type_absence="SEANCE").update(type_absence="ABSENT")

    # JOURNEE → ABSENT (positionne duree_absence = durée de la séance si la valeur était un placeholder 8h)
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

    # HEURE → PARTIEL (duree_absence contient déjà la durée partielle)
    Absence.objects.filter(type_absence="HEURE").update(type_absence="PARTIEL")

    # RETARD → PARTIEL (rattrape tout état intermédiaire de migration)
    Absence.objects.filter(type_absence="RETARD").update(type_absence="PARTIEL")


def reverse_types(apps, schema_editor):
    """Inverse : reconvertit les nouveaux types vers les anciens."""
    Absence = apps.get_model("absences", "Absence")
    Absence.objects.filter(type_absence="ABSENT").update(type_absence="SEANCE")
    Absence.objects.filter(type_absence="PARTIEL").update(type_absence="HEURE")


class Migration(migrations.Migration):

    dependencies = [
        ("absences", "0015_qr_gps_antifraud"),
    ]

    operations = [
        # Étape 1 : altère le champ pour accepter les anciennes et nouvelles valeurs pendant la migration
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
        # Étape 2 : convertit les données
        migrations.RunPython(convert_legacy_types, reverse_types),
    ]
