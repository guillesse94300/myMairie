# Scan de sécurité — Déploiement myMairie (Streamlit)

**URL cible :** https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app/
**Date du scan :** 1er mars 2026 (analyse statique complète du code source)
**Méthode :** Analyse statique exhaustive de `app.py`, `web/`, `requirements.txt`, configurations et templates.

---

## Résumé

| Niveau   | Nombre | Évolution                                |
|----------|--------|------------------------------------------|
| Critique | 0      | —                                        |
| Élevé    | 1      | Inchangé                                 |
| Moyen    | 4      | +1 (exposition rapport corrigée)         |
| Info     | 4      | +1 (IPs hardcodées)                      |

---

## 1. Secrets et gestion des accès

### 1.1 Fichier `secrets.toml` (non versionné) ✅

- `.streamlit/secrets.toml` est listé dans `.gitignore` et n'est pas suivi par Git.
- En production (Streamlit Cloud) : secrets configurés dans le dashboard (Settings → Secrets).
- **Action :** Vérifier l'historique pour s'assurer qu'il n'a jamais été commité :
  `git log -p --all -- .streamlit/secrets.toml`
  Si des secrets apparaissent : révoquer/régénérer la clé Groq et changer le token admin.

### 1.2 Authentification admin (`?admin=TOKEN`) — **[ÉLEVÉ]**

- **Comportement :** Le token est passé en query string (`st.query_params.get("admin")`) et comparé à `st.secrets.get("ADMIN_TOKEN")`.
- **Risques :** Token visible dans l'historique du navigateur, logs serveur, en-têtes Referer, partages de lien.
- **Recommandations :**
  - Utiliser un token long et aléatoire (minimum 32 caractères hex).
  - À terme : remplacer par un formulaire POST ou une session après authentification (ne pas mettre le secret en URL).

---

## 2. Rate limiting — **En place** ✅

- **Implémentation :** Limite de **5 recherches par jour** par IP (`RATE_LIMIT_MAX = 5`).
- **Whitelist :** IPs exemptées configurées dans le code.
- **Stockage :** SQLite (`data/searches.db`) — persistant entre redémarrages.
- **Périmètre :** Recherche sémantique et requêtes Agent (même compteur).

### 2.1 Bypass possible via IP spoofing — **[MOYEN]**

- **Constat :** `get_client_ip()` fait confiance à `X-Forwarded-For`, `X-Real-Ip`, `CF-Connecting-IP` dans cet ordre. Un attaquant sur certains environnements pourrait forger ces headers pour contourner la limite ou usurper une IP whitelistée.
- **Contexte atténuant :** Sur Streamlit Cloud, l'infrastructure contrôle ces headers ; le risque est réduit en production.
- **Recommandation :** Si le déploiement change (reverse proxy custom), ne faire confiance qu'au dernier IP de la chaîne `X-Forwarded-For` (IP du proxy connu), pas au premier (client potentiellement forgé).

---

## 3. Risques moyens

### 3.1 Exposition du rapport de sécurité — **CORRIGÉ** ✅

- **Constat antérieur :** `SECURITY_SCAN.md` était présent dans `static/`, servi publiquement via `enableStaticServing = true`.
- **Correction appliquée :** Le fichier a été retiré de `static/`. Le rapport est uniquement conservé à la racine du projet (non servi).

### 3.2 Dépendances sans versions fixées — **[MOYEN]**

- **Constat :** `requirements.txt` ne fixe aucune version (`pdfplumber`, `requests`, `beautifulsoup4`, `sentence-transformers`, `groq`, etc.).
- **Risque :** Mises à jour involontaires pouvant introduire des CVE ou casser des comportements.
- **Recommandation :** Figer les versions en production :
  ```
  pip freeze > requirements-lock.txt
  ```
  Auditer régulièrement avec `pip audit` ou activer Dependabot.

### 3.3 Chargement pickle (`documents.pkl`, `metadata.pkl`) — **[MOYEN]**

- **Risque :** `pickle.load()` peut exécuter du code arbitraire si les fichiers sont altérés.
- **Contexte :** Sur Streamlit Cloud, `vector_db/` provient du build ; un utilisateur distant ne peut pas remplacer ces fichiers.
- **Recommandation :** Pour tout déploiement où des fichiers externes pourraient être fournis, privilégier JSON ou un format non exécutable.

### 3.4 Django — configuration de développement exposée — **[MOYEN]**

- **Constat :** `web/config/settings.py` contient :
  - `SECRET_KEY = "dev-secret-change-in-production"` (valeur par défaut connue)
  - `DEBUG = True` (affiche les tracebacks complets)
  - `ALLOWED_HOSTS = ["*"]` (accepte toutes les origines)
- **Contexte :** Django ne semble pas déployé en production actuellement.
- **Recommandation :** Si Django est un jour exposé, corriger ces trois paramètres avant tout déploiement.

---

## 4. Points informatifs

### 4.1 IPs hardcodées dans le code source

- **Constat :** `RATE_LIMIT_WHITELIST` et `RATE_LIMIT_CREDITS_BONUS` dans `app.py` contiennent des IPs en clair dans le code source versionné.
- **Risque :** Ces IPs peuvent identifier des utilisateurs spécifiques si le dépôt est public ; elles seront dans l'historique Git.
- **Recommandation :** Déplacer ces IPs dans `st.secrets` (ex. `st.secrets.get("RATE_LIMIT_WHITELIST", "").split(",")`).

### 4.2 Erreurs Django exposées à l'utilisateur

- **Constat :** Dans `web/search/views.py` : `error = str(e)` est renvoyé au template et affiché.
- **Risque :** Peut exposer des chemins de fichiers système ou des détails d'implémentation.
- **Recommandation :** Logger `e` côté serveur et afficher un message générique à l'utilisateur.

### 4.3 Sous-processus (`subprocess`)

- Usage limité à `git log -1 --format=%ci` et `git describe --tags --abbrev=0` (app.py lignes 314–326).
- Commandes fixes, pas d'entrée utilisateur → risque faible. ✅

### 4.4 HTML dynamique avec `unsafe_allow_html=True`

- Les `st.markdown(..., unsafe_allow_html=True)` injectent uniquement :
  - Des styles CSS statiques (ligne 782)
  - Des scores numériques formatés `score:.0%` et couleurs hardcodées (lignes 1001, 1077)
  - Des URLs passées par `_safe_pdf_url()` ou `_safe_source_url()` (ligne 1087)
  - `commit_date` tronqué à 16 caractères depuis `deploy_date.txt` (ligne 860)
- Pas d'injection de contenu utilisateur brut en HTML. Risque résiduel faible. ✅

---

## 5. Bonnes pratiques en place ✅

- Secrets via `st.secrets` (pas de clés en dur pour la prod).
- Validation des URLs PDF (`_safe_pdf_url`) et sources (`_safe_source_url`) avant affichage.
- Requêtes SQLite paramétrées (pas d'injection SQL possible).
- Rate limiting par IP avec persistance SQLite.
- `secrets.toml` exclu du dépôt (`.gitignore` vérifié).
- Contenu utilisateur affiché via widgets Streamlit (échappement par défaut) ou via Markdown sans HTML.
- Django template : `{{ query }}` et `{{ error }}` auto-échappés par défaut (pas de `|safe`).
- Protection path traversal dans Django (`/documents/<filename>` vérifie `..` et `/`).

---

## 6. Checklist post-scan

- [x] Retirer `SECURITY_SCAN.md` du dossier `static/` (**FAIT**)
- [ ] Vérifier l'historique Git pour `.streamlit/secrets.toml` — révoquer si trouvé.
- [ ] Changer le token admin pour ≥32 caractères aléatoires ; envisager de ne plus le mettre en URL.
- [ ] Déplacer les IPs whitelistées dans `st.secrets` (hors historique Git).
- [ ] Figer les versions des dépendances (`pip freeze`) et auditer régulièrement.
- [ ] Si Django est déployé : corriger `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`.
- [ ] Garder les secrets uniquement dans Streamlit Cloud (Settings → Secrets).

---

*Rapport généré par analyse statique complète du code source (1er mars 2026).*
