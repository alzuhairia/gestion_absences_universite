"""
Update the notification_type_check constraint to match the current
model choices: INTERNE, ALERTE, INFO (replacing the legacy EMAIL type).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE notification
                DROP CONSTRAINT IF EXISTS notification_type_check;

                ALTER TABLE notification
                ADD CONSTRAINT notification_type_check
                CHECK (type::text = ANY (ARRAY['INTERNE', 'ALERTE', 'INFO']));
            """,
            reverse_sql="""
                ALTER TABLE notification
                DROP CONSTRAINT IF EXISTS notification_type_check;

                ALTER TABLE notification
                ADD CONSTRAINT notification_type_check
                CHECK (type::text = ANY (ARRAY['EMAIL', 'INTERNE']));
            """,
        ),
    ]
