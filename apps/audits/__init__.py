"""
Package audits du système UniAbsences.

Ce package fournit la piste d'audit en mode append-only qui enregistre
chaque action de sécurité ou critique sur le plan métier effectuée dans
l'application. Il expose :

- ``LogAudit``  — le modèle de base de données immuable (``models.py``).
- ``log_action`` — la fonction publique de création d'entrées d'audit
  (``utils.py``) ; appelée depuis les vues, les signaux et les fonctions
  de service à travers l'ensemble du code source.
- ``extract_client_ip`` / ``ratelimit_*`` — utilitaires d'extraction
  sécurisée d'IP utilisés pour la journalisation d'audit et les fonctions
  de clé de django-ratelimit (``ip_utils.py``).
- ``audit_list`` — une vue d'administration paginée et filtrable
  permettant de parcourir le journal d'audit (``views.py``).

Les enregistrements d'audit sont volontairement en écriture unique : il
n'existe aucune voie applicative pour modifier ou supprimer une entrée
``LogAudit``.

Fait partie du système d'audit UniAbsences.
"""
