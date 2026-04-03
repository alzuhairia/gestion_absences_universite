# Audit Pre-Production - Bugs Identifies (2026-04-03)

## Resume

Analyse complete du projet avant mise en production.
**Total bugs identifies : 11** (2 critiques, 4 hauts, 3 moyens, 2 bas)

---

## BUG-01 : Inconsistance EN_ATTENTE dans les calculs at-risk des dashboards [CRITIQUE]

**Probleme :** Les vues dashboard comptent `EN_ATTENTE + NON_JUSTIFIEE` pour les calculs de risque,
mais la logique metier centrale (`calculer_absence_stats`, `recalculer_eligibilite`,
`get_at_risk_count_for_queryset`) ne compte que `NON_JUSTIFIEE`.
Le test `test_pending_justification_does_not_count_as_unjustified` confirme que EN_ATTENTE
ne doit PAS penaliser l'etudiant.

**Impact :** Etudiants affiches comme "a risque" alors qu'ils ne le sont pas reellement.
Chiffres gonfles dans tous les dashboards. Incoherence avec le systeme d'eligibilite reel.

**Fichiers affectes (~20 occurrences) :**
- `apps/dashboard/views.py` : lignes 121, 310, 395
- `apps/dashboard/views_student.py` : lignes 84, 199, 420, 502, 726
- `apps/dashboard/views_professor.py` : lignes 102, 213, 393, 531
- `apps/dashboard/views_export.py` : lignes 104, 144, 231
- `apps/dashboard/views_admin_stats.py` : ligne 111
- `apps/api/views.py` : lignes 595-597, 799-800, 812-813, 946-947

**Correction :** Remplacer `statut__in=[NON_JUSTIFIEE, EN_ATTENTE]` par `statut=NON_JUSTIFIEE`
partout dans les calculs at-risk. Ajouter filtre `id_seance__date_seance__lte=today` pour
coherence avec `calculer_absence_stats()`.

---

## BUG-02 : Filtre EN_COURS manquant dans API InscriptionViewSet [HAUT]

**Probleme :** `InscriptionViewSet.get_queryset()` pour les roles ETUDIANT et PROFESSEUR
ne filtre pas par `status=EN_COURS`. Les inscriptions terminees/annulees sont exposees.

**Fichier :** `apps/api/views.py` lignes 261-272

**Correction :** Ajouter `flt["status"] = Inscription.Status.EN_COURS` pour les deux roles.

---

## BUG-03 : QRScanLog utilise CASCADE sur les FK (perte de logs d'audit) [HAUT]

**Probleme :** `QRScanLog.etudiant` et `QRScanLog.seance` utilisent `on_delete=CASCADE`.
Supprimer un utilisateur ou une seance detruit les logs d'audit de scan QR.
Les logs d'audit doivent etre immutables pour la conformite.

**Fichier :** `apps/absences/models.py` lignes 392-403

**Correction :** Changer `CASCADE` en `SET_NULL` et ajouter `null=True, blank=True` sur `etudiant`.

---

## BUG-04 : validate_niveau() manquant dans CoursWriteSerializer [HAUT]

**Probleme :** L'API accepte des valeurs `niveau` arbitraires pour la creation/mise a jour de cours.
Le modele a une contrainte choices mais le serializer ne valide pas.
`StudentSerializer` a `validate_niveau()` mais pas `CoursWriteSerializer`.

**Fichier :** `apps/api/serializers.py` lignes 146-160

**Correction :** Ajouter `validate_niveau()` identique a celui de StudentSerializer.

---

## BUG-05 : Notification.objects.create() peut annuler la mise a jour d'eligibilite [HAUT]

**Probleme :** Dans `recalculer_eligibilite()`, `Notification.objects.create()` est a l'interieur
du bloc `transaction.atomic()`. Si la notification echoue (ex: contrainte DB), tout le
changement d'eligibilite est annule. L'etudiant reste dans un etat incorrect.

**Fichier :** `apps/absences/services.py` lignes 371-409, 413-430

**Correction :** Wraper la creation de notification dans try/except pour permettre la
degradation gracieuse (l'eligibilite est mise a jour meme si la notification echoue).

---

## BUG-06 : transaction.atomic() manquant sur reset mot de passe admin [MOYEN]

**Probleme :** `admin_user_reset_password` ecrit `password` + `must_change_password` + audit log
sans wrapper transactionnel. Si le log_action echoue, le mot de passe est change sans trace.

**Fichier :** `apps/dashboard/views_admin_users.py` lignes 198-209

**Correction :** Wrapper dans `transaction.atomic()`.

---

## BUG-07 : Champs mot de passe sans max_length (vecteur DoS) [MOYEN]

**Probleme :** Plusieurs formulaires ont des CharField pour mot de passe sans `max_length`.
Un attaquant pourrait envoyer un mot de passe extremement long, consommant du CPU lors du hachage.

**Fichiers affectes :**
- `apps/accounts/forms.py` ligne 30 : CustomAuthenticationForm.password
- `apps/dashboard/forms_admin.py` lignes 221, 226 : UserForm.password, password_confirm
- `apps/enrollments/forms.py` lignes 43-46 : password_confirm

**Correction :** Ajouter `max_length=128` sur tous les champs mot de passe.

---

## BUG-08 : Dropdowns de filtres affichent les facultes/departements inactifs [MOYEN]

**Probleme :** La vue `active_courses` utilise `Faculte.objects.all()` et `Departement.objects.all()`
pour les options de filtre au lieu de filtrer par `actif=True`.

**Fichier :** `apps/dashboard/views.py` lignes 543-544

**Correction :** Ajouter `.filter(actif=True)` sur les querysets de filtre.

---

## BUG-09 : CheckConstraint manquant sur Inscription.exemption_margin [BAS]

**Probleme :** Le champ a un `MaxValueValidator(100)` mais pas de contrainte DB.
Des donnees invalides pourraient etre inserees via SQL brut ou migration.

**Fichier :** `apps/enrollments/models.py` ligne 92-97

**Correction :** Ajouter un `CheckConstraint` dans Meta.constraints + migration.

---

## BUG-10 : Template email avec autoescape off [BAS]

**Probleme :** `password_reset_email.html` utilise `{% autoescape off %}` globalement.
Bien que les variables actuelles soient sures, c'est un risque si le template est modifie.

**Fichier :** `templates/accounts/password_reset_email.html` ligne 1

**Correction :** Supprimer `{% autoescape off %}` et utiliser `{% autoescape off %}` uniquement
autour de l'URL generee.

---

## BUG-11 : QRScanRecord utilise CASCADE sur inscription/student FK [BAS]

**Probleme :** `QRScanRecord.student` et `QRScanRecord.inscription` utilisent CASCADE.
Supprimer un etudiant ou une inscription detruit les enregistrements de presence QR.

**Fichier :** `apps/absences/models.py` lignes 342-351

**Correction :** Changer en `SET_NULL` avec `null=True, blank=True`.

---

## Statut des corrections

| Bug | Severite | Statut |
|-----|----------|--------|
| BUG-01 | CRITIQUE | [x] Corrige |
| BUG-02 | HAUT | [x] Corrige |
| BUG-03 | HAUT | [x] Corrige |
| BUG-04 | HAUT | [x] Corrige |
| BUG-05 | HAUT | [x] Corrige |
| BUG-06 | MOYEN | [x] Corrige |
| BUG-07 | MOYEN | [x] Corrige |
| BUG-08 | MOYEN | [x] Corrige |
| BUG-09 | BAS | [x] Corrige |
| BUG-10 | BAS | [x] Corrige |
| BUG-11 | BAS | [x] Corrige |

**Tous les 159 tests passent apres corrections (Batch 1).**

---

## Batch 2 — 2e passe d'audit approfondie (2026-04-03)

### BUG-12 : Audit log manquant pour la creation du premier admin [HAUT]

**Probleme :** `initial_setup()` cree le premier compte admin sans aucune trace dans les logs d'audit.
C'est l'operation la plus critique du systeme et elle etait invisible.

**Fichier :** `apps/accounts/views_setup.py` ligne 94-99

**Correction :** Ajout de `log_action()` apres creation du superuser avec niveau CRITIQUE.

---

### BUG-13 : Year activation — log hors transaction + select_for_update manquant [MOYEN]

**Probleme :** `admin_academic_year_set_active()` faisait un `update(active=False)` redondant
(le model save() gere deja la desactivation des autres annees). Le `log_action()` etait hors
du `transaction.atomic()`, et `select_for_update()` manquait sur l'annee cible.

**Fichier :** `apps/dashboard/views_admin_courses.py` lignes 727-741

**Correction :** select_for_update() sur l'annee, suppression du update() redondant,
log_action() deplace a l'interieur de la transaction.

---

### BUG-14 : RoleMiddleware utilise startswith au lieu du match exact [MOYEN]

**Probleme :** `RoleMiddleware.process_view()` utilisait `path.startswith(excluded)` pour
verifier les chemins exclus du redirect "must change password". Un chemin comme
`/accounts/login/../../admin/` pourrait theoriquement bypasser la verification.

**Fichier :** `apps/accounts/middleware.py` ligne 92

**Correction :** Remplace `startswith` par `path in excluded_paths` (match exact).

---

### BUG-15 : Formulaire setup — champs mot de passe sans max_length [MOYEN]

**Probleme :** `InitialAdminForm` n'avait pas de `max_length` sur les champs password,
meme vecteur DoS que BUG-07.

**Fichier :** `apps/accounts/views_setup.py` lignes 46-58

**Correction :** Ajout de `max_length=128` sur les deux champs.

---

| Bug | Severite | Statut |
|-----|----------|--------|
| BUG-12 | HAUT | [x] Corrige |
| BUG-13 | MOYEN | [x] Corrige |
| BUG-14 | MOYEN | [x] Corrige |
| BUG-15 | MOYEN | [x] Corrige |

---

## Batch 3 — 3e passe d'audit approfondie (2026-04-03)

### BUG-16 : Filtrage date_action inconsistant dans les logs d'audit [HAUT]

**Probleme :** `admin_audit_logs()` et `admin_export_audit_csv()` utilisaient `date_action__gte`
(comparaison string sur un DateTime) pour date_from et `date_action__date__lte` pour date_to.
La comparaison `__gte` avec une string date sur un champ DateTime donne des resultats incorrects
(coerce a minuit, ignore le fuseau horaire de facon inconsistante avec `__date__lte`).

**Impact :** Les filtres de date dans les journaux d'audit retournent des enregistrements incorrects.

**Fichier :** `apps/dashboard/views_admin_settings.py` lignes 121, 197

**Correction :** Remplacer `date_action__gte` par `date_action__date__gte` dans les deux fonctions.

---

### BUG-17 : Justification sync manquant validee_par/date_validation dans edit_absence [MOYEN]

**Probleme :** `edit_absence()` synchronise `Justification.state` avec `Absence.statut` mais
ne met pas a jour `validee_par` et `date_validation`. Une justification marquee ACCEPTEE
n'a ni valideur ni date de validation, violant l'invariant de donnees.

**Impact :** Donnees de validation inconsistantes. Rapports et templates affichant validee_par
montrent NULL pour des justifications acceptees via edit_absence.

**Fichier :** `apps/absences/views_manager.py` lignes 161-174

**Correction :** Ajouter `validee_par=request.user` et `date_validation=timezone.now()` pour
ACCEPTEE et REFUSEE, et remettre a None pour EN_ATTENTE.

---

### BUG-18 : Protection injection CSV manquante sur adresse_ip [BAS]

**Probleme :** L'export CSV des logs d'audit sanitise tous les champs avec `_sanitize_csv()`
sauf `adresse_ip`. Un attaquant pourrait injecter une formule Excel via une adresse IP forgee.

**Impact :** Injection de formule Excel potentielle via l'ouverture du CSV dans un tableur.

**Fichier :** `apps/dashboard/views_admin_settings.py` ligne 231

**Correction :** Appliquer `_sanitize_csv()` sur `log.adresse_ip`.

---

| Bug | Severite | Statut |
|-----|----------|--------|
| BUG-16 | HAUT | [x] Corrige |
| BUG-17 | MOYEN | [x] Corrige |
| BUG-18 | BAS | [x] Corrige |

**Tous les 159 tests passent apres corrections (Batch 3).**
