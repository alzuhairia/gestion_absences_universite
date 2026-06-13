#!/usr/bin/env python
"""
Point d'entrée de gestion Django pour le projet UniAbsences.

Ce script est l'utilitaire en ligne de commande standard de Django. Il initialise
le module de paramètres de Django et délègue l'exécution à l'infrastructure
de commandes de gestion de Django.

Situé à la racine du projet UniAbsences.
"""

import os
import sys


def main():
    """
    Configure les paramètres Django et exécute la commande de gestion demandée.

    Définit la variable d'environnement DJANGO_SETTINGS_MODULE sur le package
    de paramètres du projet si elle n'a pas encore été définie, puis passe le
    relais à la fonction ``execute_from_command_line`` de Django avec le
    ``sys.argv`` d'origine.

    Lève :
        ImportError : si Django n'est pas installé ou si l'environnement
            virtuel n'est pas activé.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Impossible d'importer Django. Êtes-vous sûr qu'il est bien installé et "
            "disponible dans votre variable d'environnement PYTHONPATH ? Avez-vous "
            "oublié d'activer un environnement virtuel ?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
