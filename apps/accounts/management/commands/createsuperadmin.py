"""
Commande de management — création du premier compte super-administrateur.

Utilisation (local) :
    python manage.py createsuperadmin

Utilisation (Docker) :
    docker compose exec web python manage.py createsuperadmin

Mode non interactif (CI / scripts) :
    python manage.py createsuperadmin --email admin@example.com \
        --nom Admin --prenom Super --password SecurePass123!
"""

from typing import cast

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User, UserManager


class Command(BaseCommand):
    """Commande Django créant un compte super-administrateur initial (rôle ADMIN, ``is_superuser=True``)."""

    help = "Crée le premier compte super-administrateur (rôle ADMIN avec is_superuser=True)"

    def add_arguments(self, parser):
        """Déclare les options CLI : email, nom, prénom, mot de passe et mode non interactif."""
        parser.add_argument("--email", help="Adresse email de l'administrateur")
        parser.add_argument("--nom", help="Nom de famille")
        parser.add_argument("--prenom", help="Prénom")
        parser.add_argument("--password", help="Mot de passe (demandé en interactif si omis)")
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Mode non interactif (tous les champs doivent être passés en arguments)",
        )

    def handle(self, *args, **options):
        """Crée le compte après vérification d'unicité et validation de la politique mot de passe."""
        admin_count = User.objects.filter(role=User.Role.ADMIN).count()
        if admin_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"Il existe déjà {admin_count} compte(s) administrateur."
                )
            )
            if not options["no_input"]:
                confirm = input("Voulez-vous quand même créer un nouveau superadmin ? (oui/non) : ")
                if confirm.lower() not in ("oui", "o", "yes", "y"):
                    self.stdout.write("Annulé.")
                    return

        email = options["email"]
        nom = options["nom"]
        prenom = options["prenom"]
        password = options["password"]

        if options["no_input"]:
            if not all([email, nom, prenom, password]):
                raise CommandError(
                    "En mode --no-input, tous les champs sont requis : "
                    "--email, --nom, --prenom, --password"
                )
        else:
            if not email:
                email = input("Email : ").strip()
            if not nom:
                nom = input("Nom : ").strip()
            if not prenom:
                prenom = input("Prénom : ").strip()
            if not password:
                import getpass

                password = getpass.getpass("Mot de passe : ")
                password_confirm = getpass.getpass("Confirmer le mot de passe : ")
                if password != password_confirm:
                    raise CommandError("Les mots de passe ne correspondent pas.")

        if not email or not nom or not prenom or not password:
            raise CommandError("Tous les champs sont requis.")

        if User.objects.filter(email=email).exists():
            raise CommandError(f"Un utilisateur avec l'email '{email}' existe déjà.")

        if len(password) < 8:
            raise CommandError("Le mot de passe doit contenir au moins 8 caractères.")

        user_manager = cast(UserManager, User.objects)

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            temp_user = User(email=email, nom=nom, prenom=prenom)
            validate_password(password, user=temp_user)
        except ValidationError as e:
            raise CommandError(
                "Le mot de passe ne respecte pas les règles de sécurité :\n"
                + "\n".join(e.messages)
            )

        user = user_manager.create_superuser(
            email=email,
            nom=nom,
            prenom=prenom,
            password=password,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuperadmin créé avec succès !\n"
                f"  Email : {user.email}\n"
                f"  Nom   : {user.get_full_name()}\n"
                f"  Rôle  : {user.role}\n\n"
                f"Connectez-vous sur /accounts/login/ ou /admin/"
            )
        )
