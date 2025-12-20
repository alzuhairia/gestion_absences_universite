# apps/accounts/migrations/0001_initial.py
from django.db import migrations, models
import django.contrib.auth.models
import django.contrib.auth.validators
from django.utils import timezone

class Migration(migrations.Migration):
    initial = True
    
    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]
    
    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, verbose_name='superuser status')),
                ('username', models.CharField(max_length=150, unique=True, verbose_name='username')),
                ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, verbose_name='active')),
                ('date_joined', models.DateTimeField(default=timezone.now, verbose_name='date joined')),
                # Champs personnalisés
                ('user_type', models.CharField(max_length=20, choices=[
                    ('student', 'Étudiant'),
                    ('professor', 'Enseignant'),
                    ('admin', 'Administrateur'),
                ])),
                ('phone', models.CharField(max_length=20, blank=True)),
                ('groups', models.ManyToManyField(blank=True, to='auth.Group', related_name='custom_user_set')),
                ('user_permissions', models.ManyToManyField(blank=True, to='auth.Permission', related_name='custom_user_set')),
            ],
            options={
                'db_table': 'utilisateur',
                'verbose_name': 'utilisateur',
                'verbose_name_plural': 'utilisateurs',
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
    ]