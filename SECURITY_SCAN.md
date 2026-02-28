# Scan de sécurité — Déploiement myMairie (Streamlit)

**URL cible :** https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app/  
**Date du scan :** 28 février 2025 (mise à jour complète)

**Méthode :** Analyse statique du code source et des configurations. Le chargement direct de l’URL a expiré côté outil ; le rapport s’appuie sur le dépôt Git et les fichiers du projet.

---

## Résumé

| Niveau   | Nombre | Évolution depuis dernier scan      |
|----------|--------|-------------------------------------|
| Critique | 0      | —                                   |
| Élevé    | 1      | Rate limiting désormais en place    |
| Moyen    | 3      | + exposition possible du rapport   |
| Info     | 3      | —                                   |

---

## 1. Secrets et gestion des accès

### 1.1 Fichier `secrets.toml` (non versionné)

- **Vérification :** `.streamlit/secrets.toml` est listé dans `.gitignore` et **n’est pas suivi** par Git (`git check-ignore` confirme).
- **En production (Streamlit Cloud) :** Les secrets doivent être configurés dans le dashboard (Settings → Secrets), pas via le dépôt.
- **Action recommandée :** Vérifier l’historique au cas où le fichier aurait été commité par le passé :  
  `git log -p --all -- .streamlit/secrets.toml`  
  Si des secrets apparaissent : révoquer/régénérer la clé Groq et changer le token admin.

### 1.2 Authentification admin (`?admin=TOKEN`) — **Élevé**

- **Comportement :** Le token admin est passé en query string (`st.query_params.get("admin")`) et comparé à `st.secrets.get("ADMIN_TOKEN")`.
- **Risques :** Le token apparaît dans l’historique du navigateur, les logs serveur, les en-têtes Referer et les partages de lien.
- **Recommandations :**
  - Utiliser un token long et aléatoire (ex. 32 caractères hex).
  - À terme : ne pas mettre le token dans l’URL (formulaire POST ou session après login).

---

## 2. Rate limiting — **En place**

- **Implémentation :** Limite de **5 recherches par heure** par IP (`RATE_LIMIT_MAX = 5`, `RATE_LIMIT_WINDOW = 1 h`).
- **Whitelist :** IP `86.208.120.20` exemptée.
- **Périmètre :** Recherche sémantique et requêtes Agent Casimir (même compteur).
- **Stockage :** En mémoire (`_rate_limit_store`). Les timestamps au-delà de la fenêtre sont purgés.
- **Affichage :** IP et nombre de recherches restantes (X/5 ou ∞) dans le bandeau.

---

## 3. Risques moyens

### 3.1 Exposition du rapport de sécurité via `static/`

- **Constat :** Une copie de `SECURITY_SCAN.md` est présente dans `static/`. Avec `enableStaticServing = true` dans `.streamlit/config.toml`, les fichiers sous `static/` sont servis (ex. `…/app/static/…`).
- **Risque :** Un attaquant peut lire le rapport et s’appuyer sur les recommandations pour cibler l’app.
- **Recommandation :** Retirer `SECURITY_SCAN.md` du dossier `static/` (ou ne pas le copier dedans). Garder le rapport uniquement à la racine du projet et ne pas le déployer en tant que ressource statique publique.

### 3.2 Liens construits à partir des métadonnées (XSS / URL)

- **Mitigation en place :** `_safe_pdf_url(rel_path)` rejette `..`, `/`, et les schemes `javascript:`, `data:`, `vbscript:`. `_safe_source_url(url)` n’accepte que `http://` et `https://`.
- **Utilisation :** Ces helpers sont utilisés pour les liens PDF, les sources de l’Agent et la section Documents.
- **Risque résiduel :** Faible tant que les métadonnées (pickle) ne sont pas modifiées par un acteur malveillant.

### 3.3 Chargement de pickle (`documents.pkl`, `metadata.pkl`)

- **Risque :** La désérialisation `pickle.load()` peut exécuter du code si les fichiers sont altérés.
- **Contexte :** Sur Streamlit Cloud, les fichiers sous `vector_db/` proviennent du dépôt ou du build ; un utilisateur distant ne peut pas les remplacer.
- **Recommandation :** Pour tout déploiement où des utilisateurs pourraient fournir ou modifier des données, privilégier un format non exécutable (JSON, base vectorielle externe).

---

## 4. Autres points

### 4.1 Dépendances (`requirements.txt`)

- Aucune version fixée (pas de `package==x.y.z`). Cela peut faciliter des mises à jour involontaires ou des failles connues.
- **Recommandation :** Figer les versions en production (`pip freeze` ou outil type `pip-tools`) et auditer régulièrement (ex. `pip audit` ou Dependabot).

### 4.2 Sous-processus (`subprocess`)

- Utilisation limitée à `git log` et `git describe` pour les infos de déploiement (avec repli sur `deploy_date.txt`). Commandes fixes, pas d’entrée utilisateur → risque faible.

### 4.3 HTML dynamique

- Quelques `st.markdown(..., unsafe_allow_html=True)` avec chaînes contrôlées (styles, liens construits via `_safe_pdf_url` / `_safe_source_url`). Pas d’injection de contenu utilisateur brut en HTML.

### 4.4 Django (`web/config/settings.py`)

- `SECRET_KEY = "dev-secret-change-in-production"` et `ALLOWED_HOSTS = ["*"]`. À corriger si l’application Django est un jour exposée en production.

---

## 5. Bonnes pratiques en place

- Secrets lus via `st.secrets` (pas de clés en dur pour la prod dans le code).
- Validation des URLs des PDF et des sources avant affichage.
- Rate limiting par IP avec whitelist.
- Pas d’exposition de `secrets.toml` dans le dépôt (vérifié).
- Contenu utilisateur affiché via les widgets Streamlit (échappement par défaut).

---

## 6. Checklist post-scan

- [ ] Vérifier l’historique Git pour `.streamlit/secrets.toml` et révoquer les clés si besoin.
- [ ] Changer le token admin pour une valeur longue et aléatoire ; éviter de le mettre en URL si possible.
- [ ] **Retirer `SECURITY_SCAN.md` du dossier `static/`** (ou ne pas le servir publiquement).
- [ ] Garder les secrets uniquement dans Streamlit Cloud (Settings → Secrets).
- [ ] En production : figer les versions des dépendances et les auditer régulièrement.

---

*Rapport généré par analyse du code source et des configurations. URL live non chargée (timeout).*
