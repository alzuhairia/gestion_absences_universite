"""Paquet de l'application absences (cœur métier du projet).

Modélise les absences (enregistrement manuel par le professeur ou par
scan QR de l'étudiant), les justifications (dépôt par l'étudiant,
décision par le secrétariat), le calcul du taux d'absence par cours et
les seuils de blocage. Expose également les services métier
(``services/``), les vues par rôle (``views/``) et les signaux
(``signals``) qui déclenchent les notifications email.

Note : ``default_app_config`` est conservé par compatibilité avec
d'éventuels imports historiques, bien que Django ≥ 3.2 le détecte
automatiquement à partir de la classe ``AbsencesConfig``.
"""
default_app_config = "apps.absences.apps.AbsencesConfig"
