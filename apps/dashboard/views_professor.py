"""
Hub des vues du tableau de bord professeur pour le système UniAbsences.

Ce module est un hub de réexport qui agrège tous les symboles de vues du tableau
de bord destinées aux professeurs depuis les sous-modules dédiés vers un seul
espace de noms stable, de sorte que ``dashboard/urls.py`` puisse importer depuis
un unique emplacement. Aucune logique n'est implémentée ici ; voir les
sous-modules individuels pour la documentation complète.

Responsabilités des sous-modules
--------------------------------
``views_professor_dashboard.py``
    ``instructor_dashboard`` — page d'accueil affichant les KPI (cours actifs,
    séances tenues / à venir, total des absences) et une courte liste
    d'étudiants à risque ou exemptés.

``views_professor_course_detail.py``
    ``instructor_course_detail`` — page de détail avec onglets pour un cours
    unique : étudiants inscrits avec taux d'absence individuels et niveaux de
    risque prédictifs, historique des séances avec jetons QR actifs, et
    statistiques agrégées.

``views_professor_course_list.py``
    ``instructor_courses`` — liste paginée de tous les cours actifs assignés
    au professeur, chacun avec le nombre d'inscrits, le nombre de séances et
    le nombre d'étudiants à risque.

``views_professor_sessions.py``
    ``instructor_sessions``   — historique des séances paginé, groupé par cours.
    ``instructor_statistics`` — agrégation des statistiques par cours (taux
    d'absence moyen, nombre d'étudiants à risque, total des absences).

Note : toutes les vues de ce hub sont en lecture seule pour les données
étudiantes. Aucune action administrative (modification d'inscription, encodage
d'absence, etc.) n'est permise ici.

Fait partie du système de tableau de bord UniAbsences.
"""

# Réexporter toutes les vues professeur pour compatibilité ascendante avec views.py et urls.py.
# Le nouveau code doit importer directement depuis le sous-module spécifique.

from apps.dashboard.views_professor_dashboard import (  # noqa: F401
    instructor_dashboard,
)

from apps.dashboard.views_professor_course_detail import (  # noqa: F401
    instructor_course_detail,
)

from apps.dashboard.views_professor_course_list import (  # noqa: F401
    instructor_courses,
)

from apps.dashboard.views_professor_sessions import (  # noqa: F401
    instructor_sessions,
    instructor_statistics,
)
