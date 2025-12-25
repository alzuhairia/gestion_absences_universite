"""
Utilitaire pour configurer Django dans les scripts.
À utiliser dans tous les scripts pour garantir l'accès à config.settings.
"""
import os
import sys
from pathlib import Path

def setup_django():
    """
    Configure l'environnement Django pour les scripts.
    Ajoute le répertoire racine du projet au PYTHONPATH.
    """
    # Obtenir le répertoire racine du projet
    # Ce fichier est dans scripts/, donc parent.parent = racine
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    project_root = str(BASE_DIR)
    
    # Ajouter le répertoire racine au PYTHONPATH s'il n'y est pas déjà
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # Configurer Django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    
    # Importer et initialiser Django
    import django
    django.setup()

