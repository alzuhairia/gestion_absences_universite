"""Paquet de l'application dashboard (tableaux de bord par rôle).

Centralise toutes les vues / formulaires / décorateurs spécifiques à
chaque rôle (admin, secrétaire, professeur, étudiant). Ne possède pas
de modèles métier propres : c'est une app « façade » qui orchestre
des données venant d'autres apps (absences, academics, enrollments,
audits, accounts).
"""
