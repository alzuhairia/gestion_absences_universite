"""
Package academic_sessions du système UniAbsences.

Ce package gère la dimension temporelle du calendrier académique :
les années académiques (AnneeAcademique) et les séances de cours
individuelles (Seance). Tous les enregistrements de présence, les
inscriptions et les attributions de cours sont rattachés à une année
académique définie ici.

Une seule année académique peut être marquée comme active à la fois.
L'activation d'une nouvelle année désactive automatiquement la
précédente et clôture toute inscription étudiante encore ouverte pour
l'année sortante.

Fait partie de la structure académique d'UniAbsences.
"""
