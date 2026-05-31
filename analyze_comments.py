"""Outil ad-hoc d'audit de couverture des docstrings.

Parcourt tous les fichiers ``.py`` du projet (hors ``venv``,
``__pycache__``, ``.git`` et migrations) et, via le module ``ast``,
détecte pour chacun :
    - l'absence de docstring de module
    - l'absence de docstring sur chaque fonction publique
    - l'absence de docstring sur chaque classe

Le résultat est écrit dans ``missing_comments.txt`` au format
``<chemin>: <N> items missing docstrings``, trié décroissant par
nombre d'éléments manquants — pratique pour prioriser les fichiers
à documenter en premier.

Exclusion volontaire : les fichiers ``__init__.py`` sont ignorés car
beaucoup ne sont que des marqueurs de paquet.

Usage : ``python analyze_comments.py``
"""
import ast
import os

def check_file(filepath):
    """Retourne la liste des éléments sans docstring détectés dans le fichier ``filepath``."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
        
        missing = []
        if not ast.get_docstring(tree):
            missing.append("Module docstring")
            
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not ast.get_docstring(node) and not node.name.startswith('__'):
                    missing.append(f"Function {node.name}")
            elif isinstance(node, ast.ClassDef):
                if not ast.get_docstring(node):
                    missing.append(f"Class {node.name}")
                    
        return missing
    except Exception as e:
        return [f"Error parsing: {e}"]

total_missing = {}
for root, dirs, files in os.walk('.'):
    if 'venv' in root or '__pycache__' in root or '.git' in root or 'migrations' in root:
        continue
    for file in files:
        if file.endswith('.py') and not file == '__init__.py':
            filepath = os.path.join(root, file)
            missing = check_file(filepath)
            if missing:
                total_missing[filepath] = missing

with open('missing_comments.txt', 'w', encoding='utf-8') as f:
    for filepath, missing in sorted(total_missing.items(), key=lambda x: len(x[1]), reverse=True):
        f.write(f"{filepath}: {len(missing)} items missing docstrings\n")
