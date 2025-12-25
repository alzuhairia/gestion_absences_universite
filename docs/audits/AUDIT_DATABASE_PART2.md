# 🗃️ AUDIT BASE DE DONNÉES - PARTIE 2

## 📊 ANALYSE DES MODÈLES CLÉS

---

## 1️⃣ MODÈLE USER / ROLE

### ✅ Points Positifs
- Utilisation de `TextChoices` pour les rôles (bonne pratique)
- Contrainte `unique=True` sur email
- Relations FK bien définies
- Soft delete avec `actif` (pas de suppression physique)

### ⚠️ Problèmes Identifiés

#### Problème 1.1: `last_login = None` (ligne 160)
```python
last_login = None  # On désactive explicitement ce champ
```
**Impact:** Django s'attend à ce champ. Peut causer des problèmes avec certains middlewares.
**Recommandation:** Utiliser `null=True, blank=True` au lieu de désactiver.

#### Problème 1.2: Pas d'index sur `role` et `actif`
**Impact:** Requêtes de filtrage par rôle/statut peuvent être lentes.
**Recommandation:** Ajouter `db_index=True` sur ces champs.

---

## 2️⃣ MODÈLES ACADÉMIQUES (Faculté / Département / Cours)

### ✅ Points Positifs
- Hiérarchie claire: Faculte → Departement → Cours
- Contraintes `unique=True` sur `nom_faculte` et `code_cours`
- Soft delete avec `actif`
- ManyToMany pour prérequis (bonne normalisation)

### ❌ Problèmes Critiques

#### Problème 2.1: `models.DO_NOTHING` partout
```python
# apps/academics/models.py
id_faculte = models.ForeignKey(Faculte, models.DO_NOTHING, ...)
id_departement = models.ForeignKey(Departement, models.DO_NOTHING, ...)
```
**Impact CRITIQUE:** 
- Si une Faculté est supprimée, les Départements deviennent orphelins
- Si un Département est supprimé, les Cours deviennent orphelins
- Risque d'intégrité référentielle violée

**Recommandation:**
```python
# Pour Faculte (peut être supprimée si aucun département)
id_faculte = models.ForeignKey(Faculte, models.PROTECT, ...)

# Pour Departement (peut être supprimé si aucun cours)
id_departement = models.ForeignKey(Departement, models.PROTECT, ...)

# Pour Cours.professeur (peut être NULL si prof supprimé)
professeur = models.ForeignKey('accounts.User', models.SET_NULL, null=True, ...)
```

#### Problème 2.2: Duplication `seuil_absence`
- `Cours.seuil_absence` (par cours)
- `SystemSettings.default_absence_threshold` (global)

**Impact:** 
- Logique métier dupliquée
- Risque d'incohérence si le seuil global change

**Recommandation:**
- Garder `Cours.seuil_absence` pour personnalisation par cours
- Utiliser `SystemSettings.default_absence_threshold` uniquement comme valeur par défaut lors de la création
- Ajouter une méthode `Cours.get_seuil_absence()` qui retourne `seuil_absence` ou `default_absence_threshold` si NULL

#### Problème 2.3: Pas de contrainte CHECK pour `seuil_absence`
**Impact:** Valeurs négatives ou > 100% possibles.
**Recommandation:** Ajouter validation dans le modèle ou contrainte DB.

---

## 3️⃣ MODÈLE ANNÉE ACADÉMIQUE

### ✅ Points Positifs
- `unique=True` sur `libelle`
- Soft delete conceptuel avec `active`

### ❌ Problème Critique

#### Problème 3.1: Pas de contrainte DB pour "une seule année active"
**Impact:** Plusieurs années peuvent être `active=True` simultanément.
**Solution actuelle:** Géré en Python (ligne 496 `views_admin.py`)

**Recommandation:** 
```python
# Option 1: Contrainte unique partielle (PostgreSQL)
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=['active'],
            condition=models.Q(active=True),
            name='unique_active_year'
        )
    ]

# Option 2: Signal pre_save pour forcer une seule année active
```

---

## 4️⃣ MODÈLE SYSTEM SETTINGS

### ✅ Points Positifs
- Pattern singleton bien implémenté
- Historique avec `last_modified` et `modified_by`
- Bonne séparation des préoccupations

### ⚠️ Problèmes

#### Problème 4.1: Singleton forcé dans `save()` sans contrainte DB
```python
def save(self, *args, **kwargs):
    self.id = 1
    super().save(*args, **kwargs)
```
**Impact:** Si plusieurs instances sont créées, seule la dernière est utilisée.

**Recommandation:**
```python
class Meta:
    constraints = [
        models.CheckConstraint(
            check=models.Q(id=1),
            name='system_settings_singleton'
        )
    ]
```

#### Problème 4.2: Pas d'historique des changements
**Impact:** Impossible de voir l'historique des modifications de paramètres.

**Recommandation:** Créer un modèle `SystemSettingsHistory` pour tracker les changements.

---

## 5️⃣ MODÈLE LOG AUDIT

### ✅ Points Positifs
- Read-only (pas de suppression)
- IP tracking
- Date/heure automatique

### ❌ Problèmes Critiques

#### Problème 5.1: `models.DO_NOTHING` sur `id_utilisateur`
```python
id_utilisateur = models.ForeignKey(..., models.DO_NOTHING, ...)
```
**Impact CRITIQUE:** Si un utilisateur est supprimé, les logs deviennent orphelins.
**Recommandation:** Utiliser `models.PROTECT` pour empêcher la suppression d'utilisateurs avec des logs.

#### Problème 5.2: Pas de champ structuré pour l'objet affecté
**Impact:** Recherche difficile des logs liés à un objet spécifique (ex: "tous les logs pour le cours X").

**Recommandation:**
```python
objet_type = models.CharField(max_length=50, null=True, blank=True)  # 'COURS', 'USER', 'FACULTE', etc.
objet_id = models.IntegerField(null=True, blank=True)  # ID de l'objet
```

#### Problème 5.3: Pas d'index sur `date_action` et `id_utilisateur`
**Impact:** Requêtes de filtrage lentes.
**Recommandation:** Ajouter `db_index=True`.

---

## 6️⃣ MODÈLE INSCRIPTION

### ✅ Points Positifs
- Contrainte `unique_together` sur (étudiant, cours, année)
- Relations FK bien définies
- Champs d'exemption bien structurés

### ❌ Problèmes Critiques

#### Problème 6.1: `models.DO_NOTHING` partout
**Impact:** Données orphelines si suppression.

**Recommandation:**
```python
id_etudiant = models.ForeignKey(..., models.PROTECT, ...)  # Empêcher suppression
id_cours = models.ForeignKey(..., models.PROTECT, ...)  # Empêcher suppression
id_annee = models.ForeignKey(..., models.PROTECT, ...)  # Empêcher suppression
```

#### Problème 6.2: `eligible_examen` calculé mais stocké
**Impact:** Risque de désynchronisation si calcul non déclenché.

**Analyse:**
- Calculé dans `services.py:recalculer_eligibilite()`
- Déclenché par signal `post_save` sur `Absence`
- **Risque:** Si signal non déclenché ou calcul manuel, désynchronisation

**Recommandation:**
```python
# Option 1: Propriété calculée (pas de stockage)
@property
def eligible_examen(self):
    # Calcul à la volée
    total_absence = Absence.objects.filter(
        id_inscription=self,
        statut='NON_JUSTIFIEE'
    ).aggregate(total=Sum('duree_absence'))['total'] or 0
    taux = (total_absence / self.id_cours.nombre_total_periodes) * 100
    return taux < self.id_cours.seuil_absence and not self.exemption_40

# Option 2: Garder stockage mais ajouter validation
def save(self, *args, **kwargs):
    # Recalculer avant sauvegarde
    super().save(*args, **kwargs)
    recalculer_eligibilite(self)
```

#### Problème 6.3: Pas d'index sur `status` et `eligible_examen`
**Impact:** Requêtes de filtrage lentes.
**Recommandation:** Ajouter `db_index=True`.

---

## 7️⃣ MODÈLE ABSENCE

### ✅ Points Positifs
- Relations FK bien définies
- Types et statuts avec `TextChoices`

### ❌ Problèmes Critiques

#### Problème 7.1: `models.DO_NOTHING` partout
**Impact:** Données orphelines.

**Recommandation:**
```python
id_inscription = models.ForeignKey(..., models.PROTECT, ...)
id_seance = models.ForeignKey(..., models.PROTECT, ...)
encodee_par = models.ForeignKey(..., models.PROTECT, ...)
```

#### Problème 7.2: Pas de contrainte CHECK pour `duree_absence`
**Impact:** Valeurs négatives possibles.
**Recommandation:** Validation dans le modèle ou contrainte DB.

#### Problème 7.3: Pas d'index sur `statut` et `date_seance`
**Impact:** Requêtes de filtrage lentes.
**Recommandation:** Ajouter `db_index=True`.

---

## 8️⃣ MODÈLE JUSTIFICATION

### ✅ Points Positifs
- `OneToOneField` avec Absence (bonne normalisation)
- État avec `state` (EN_ATTENTE, ACCEPTEE, REFUSEE)

### ❌ Problème

#### Problème 8.1: Duplication `validee` (deprecated) + `state`
```python
validee = models.BooleanField(default=False)  # Deprecated
state = models.CharField(..., choices=STATE_CHOICES, ...)  # Actuel
```
**Impact:** Confusion, risque d'incohérence.

**Recommandation:**
- Supprimer `validee` après migration
- Utiliser uniquement `state`

#### Problème 8.2: `models.DO_NOTHING` sur `id_absence` et `validee_par`
**Impact:** Données orphelines.

**Recommandation:**
```python
id_absence = models.OneToOneField(..., models.PROTECT, ...)
validee_par = models.ForeignKey(..., models.SET_NULL, null=True, ...)
```

---

## 9️⃣ MODÈLES NOTIFICATION & MESSAGE

### ⚠️ Problèmes

#### Problème 9.1: `models.DO_NOTHING` partout
**Impact:** Données orphelines.

**Recommandation:**
```python
# Notification
id_utilisateur = models.ForeignKey(..., models.CASCADE, ...)  # Supprimer si user supprimé

# Message
expediteur = models.ForeignKey(..., models.SET_NULL, null=True, ...)
destinataire = models.ForeignKey(..., models.SET_NULL, null=True, ...)
```

#### Problème 9.2: Pas d'index sur `lue` et `date_envoi`
**Impact:** Requêtes de filtrage lentes.
**Recommandation:** Ajouter `db_index=True`.

---

## 📋 RÉSUMÉ DES PROBLÈMES PAR PRIORITÉ

### 🔴 CRITIQUE (Doit être corrigé)

1. **`models.DO_NOTHING` partout** → Risque d'intégrité référentielle
   - **Impact:** Données orphelines, corruption possible
   - **Fichiers:** Tous les modèles

2. **`eligible_examen` stocké mais calculé** → Risque de désynchronisation
   - **Impact:** Données incorrectes si calcul non déclenché
   - **Fichier:** `apps/enrollments/models.py`

3. **Pas de contrainte pour année active unique**
   - **Impact:** Plusieurs années actives simultanément
   - **Fichier:** `apps/academic_sessions/models.py`

### 🟡 HAUTE PRIORITÉ (Recommandé)

4. **Duplication `seuil_absence`** → Logique métier dupliquée
5. **Pas d'index sur champs fréquemment recherchés**
6. **Duplication `validee` + `state` dans Justification**
7. **Pas de champ structuré pour objet affecté dans LogAudit**

### 🟢 AMÉLIORATION (Optionnel)

8. **Pas d'historique des changements SystemSettings**
9. **Pas de contraintes CHECK pour valeurs numériques**
10. **`last_login = None` dans User**

---

## 🛠️ RECOMMANDATIONS D'AMÉLIORATION

### 1. Normalisation

#### Amélioration 1.1: Créer modèle d'historique pour SystemSettings
```python
class SystemSettingsHistory(models.Model):
    settings = models.ForeignKey(SystemSettings, on_delete=models.CASCADE)
    modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    modified_at = models.DateTimeField(auto_now_add=True)
    field_name = models.CharField(max_length=50)
    old_value = models.TextField()
    new_value = models.TextField()
    reason = models.TextField(blank=True)
```

#### Amélioration 1.2: Structurer LogAudit
```python
class LogAudit(models.Model):
    # ... champs existants ...
    objet_type = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    objet_id = models.IntegerField(null=True, blank=True, db_index=True)
    niveau = models.CharField(max_length=20, choices=[('INFO', 'Info'), ('WARNING', 'Warning'), ('CRITIQUE', 'Critique')])
    
    class Meta:
        indexes = [
            models.Index(fields=['date_action', 'niveau']),
            models.Index(fields=['objet_type', 'objet_id']),
        ]
```

### 2. Simplification

#### Amélioration 2.1: Supprimer `validee` deprecated
- Migration pour supprimer le champ
- Mettre à jour le code pour utiliser uniquement `state`

#### Amélioration 2.2: Méthode helper pour seuil d'absence
```python
# Dans Cours
def get_seuil_absence(self):
    """Retourne le seuil du cours ou le seuil par défaut"""
    if self.seuil_absence is not None:
        return self.seuil_absence
    return SystemSettings.get_settings().default_absence_threshold
```

### 3. Meilleur Nommage

#### Amélioration 3.1: Renommer pour clarté
- `id_utilisateur` → `utilisateur` (Django convention)
- `id_etudiant` → `etudiant`
- `id_cours` → `cours`
- `id_annee` → `annee_academique`

**Note:** Garder les noms actuels si la base de données existante les utilise.

---

## ✅ VALIDATION FINALE

| Aspect | État | Score |
|--------|------|-------|
| **Normalisation** | ⚠️ **AMÉLIORABLE** | 6/10 |
| **Intégrité Référentielle** | ❌ **CRITIQUE** | 3/10 |
| **Historique/Tracking** | ⚠️ **PARTIEL** | 5/10 |
| **Index/Performance** | ⚠️ **AMÉLIORABLE** | 4/10 |
| **Contraintes DB** | ⚠️ **INSUFFISANT** | 4/10 |

**SCORE GLOBAL: 4.4/10** ⚠️ **AMÉLIORATION NÉCESSAIRE**

---

## 🎯 PLAN D'ACTION RECOMMANDÉ

### Phase 1: Corrections Critiques (Urgent)
1. Remplacer tous les `DO_NOTHING` par `PROTECT` ou `SET_NULL` approprié
2. Ajouter contrainte pour année active unique
3. Résoudre la duplication `eligible_examen` (propriété calculée ou validation)

### Phase 2: Améliorations Haute Priorité (Court terme)
4. Ajouter index sur champs fréquemment recherchés
5. Supprimer `validee` deprecated
6. Structurer LogAudit avec `objet_type` et `objet_id`

### Phase 3: Optimisations (Moyen terme)
7. Créer modèle d'historique SystemSettings
8. Ajouter contraintes CHECK pour valeurs numériques
9. Améliorer nommage (si migration possible)

---

**STATUT: ⚠️ CORRECTIONS CRITIQUES NÉCESSAIRES**

