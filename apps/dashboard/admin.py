"""
Enregistrement du site d'administration Django pour l'application dashboard UniAbsences.

Ce fichier est volontairement minimaliste. Le singleton ``SystemSettings``
est géré exclusivement via l'interface d'administration personnalisée
(``views_admin_settings_form.py``) afin de garantir la contrainte de singleton
et de maintenir la piste d'audit. Son enregistrement dans le panneau
d'administration standard de Django est donc délibérément omis.

Partie du système dashboard UniAbsences.
"""
