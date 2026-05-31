"""
Package academics pour le système UniAbsences.

Ce package modélise la hiérarchie académique à trois niveaux de l'université :
les facultés (Faculte), les départements (Departement) et les cours (Cours). Les
trois entités prennent en charge la suppression logique via un drapeau booléen
``actif`` afin que les données historiques de présence ne soient jamais
orphelines lorsqu'une unité structurelle est retirée.

Partie de la structure académique d'UniAbsences.
"""
