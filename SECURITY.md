# Politique de sécurité

## Versions prises en charge

| Version | Prise en charge    |
|---------|--------------------|
| 1.0.x   | :white_check_mark: |

## Signaler une vulnérabilité

Si vous découvrez une vulnérabilité de sécurité dans ce projet, merci de la signaler de manière responsable.

**N'ouvrez PAS d'issue publique sur GitHub.**

Envoyez plutôt un email à **alzuhairia@proton.me** avec :

- Une description de la vulnérabilité
- Les étapes de reproduction
- L'impact potentiel
- Un correctif suggéré (le cas échéant)

Nous accuserons réception sous **48 heures** et viserons une publication de correctif sous **7 jours** pour les problèmes critiques.

## Mesures de sécurité

Ce projet implémente les pratiques de sécurité suivantes :

- **Portes de sécurité CI/CD** : Bandit (SAST), pip-audit (vulnérabilités des dépendances), Gitleaks (scan des secrets), Trivy (scan de conteneur), CodeQL (analyse sémantique)
- **Durcissement à l'exécution** : protection CSRF, rate limiting, SRI sur les ressources CDN, CSP basée sur nonce, HSTS, cookies sécurisés
- **Sécurité des sessions** : timeout d'inactivité, expiration de session, durcissement des cookies (Secure, HttpOnly, SameSite)
- **Contrôle d'accès** : décorateurs basés sur les rôles, vérifications de permissions côté serveur, changement de mot de passe forcé à la première connexion, application des méthodes HTTP sur toutes les vues
- **Anti-fraude présence QR** : vérification GPS avec rayon configurable, journalisation d'audit des scans, marquage de suspicion basé sur la distance
- **Piste d'audit** : toutes les actions sensibles sont journalisées avec l'utilisateur, l'horodatage et les détails de l'action
- **Sécurité des conteneurs** : utilisateur non-root, système de fichiers en lecture seule, no-new-privileges, image de base minimale

## Dépendances

Les dépendances sont surveillées via :
- `pip-audit` en CI (bloque sur les vulnérabilités corrigibles, allowlist pour les exceptions connues)
- Scan de conteneur Trivy (CVE OS + bibliothèques)
- Action de revue de dépendances sur les pull requests (bloque les ajouts à sévérité élevée)
