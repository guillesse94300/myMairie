# Scan de sécurité — Déploiement myMairie (Streamlit)

**URL cible :** https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app/  
**Date :** 28 février 2025

---

## Résumé

| Niveau | Nombre |
|--------|--------|
| Critique | 1 |
| Élevé | 2 |
| Moyen | 2 |
| Info | 2 |

---

## 1. Critique

### 1.1 Secrets et fichier `secrets.toml`

- **État :** Le fichier `.streamlit/secrets.toml` est bien listé dans `.gitignore` et **n’est pas suivi** par Git (`git ls-files` ne le remonte pas). Sur Streamlit Cloud, les secrets se configurent dans le dashboard (Settings → Secrets), pas via le dépôt.
- **Risque :** Si `secrets.toml` a un jour été commité, les clés restent dans l’historique Git (ADMIN_TOKEN, GROQ_API_KEY).
- **Actions :**
  1. Vérifier l’historique : `git log -p --all -- .streamlit/secrets.toml`
  2. Si le fichier est apparu dans l’historique : **révoquer et régénérer** la clé Groq (console.groq.com) et **changer** le mot de passe admin.
  3. Ne jamais committer `secrets.toml` ; utiliser uniquement les secrets Streamlit Cloud en production.

---

## 2. Élevé

### 2.1 Authentification admin par paramètre d’URL (`?admin=TOKEN`)

- **Comportement actuel :** Le token admin est passé en query string. Il apparaît dans l’historique du navigateur, les logs serveur, les en-têtes Referer et les partages de lien.
- **Recommandations :**
  - Utiliser un token long et aléatoire (ex. 32 caractères hex).
  - Idéalement : ne pas mettre le token dans l’URL ; utiliser un formulaire (mot de passe en POST) ou une session côté serveur après une page de login, et ne pas afficher le token dans l’UI.

### 2.2 Pas de limitation de débit (rate limiting)

- **Risque :** Un attaquant qui obtiendrait la clé Groq (fuite, historique Git) ou exploiterait une faille pourrait envoyer un grand nombre de requêtes (coût / abus).
- **Recommandations :**
  - S’appuyer sur les limites Groq (quota gratuit/payant).
  - Optionnel : ajouter un rate limiting côté app (ex. par IP ou par session) pour l’onglet Agent, pour limiter l’abus même sans fuite de clé.

---

## 3. Moyen

### 3.1 Liens construits à partir des métadonnées (XSS / URL non sécurisées)

- **Comportement :** Les URLs des PDF et des sources sont construites avec `meta.get("filename")`, `meta.get("rel_path")` et `meta.get("source_url")`. Ces valeurs viennent des fichiers pickle générés par `ingest.py`. Si les métadonnées étaient un jour corrompues ou injectées (ex. `javascript:...` ou `data:...`), un lien malveillant pourrait être affiché.
- **Recommandation :** Valider/sanitiser toutes les URLs avant de les afficher : n’accepter que des chemins relatifs sûrs (pas de `..`) ou des URLs `https?://` avec domaine autorisé. Une fonction dédiée (ex. `_safe_pdf_url()`) a été ajoutée dans `app.py` pour limiter ce risque.

### 3.2 Chargement de pickle (`documents.pkl`, `metadata.pkl`)

- **Risque :** `pickle` peut exécuter du code arbitraire à la désérialisation. Si un attaquant pouvait remplacer ces fichiers sur le serveur, il pourrait obtenir une exécution de code.
- **Contexte :** Sur Streamlit Cloud, le système de fichiers de l’app est dérivé du dépôt (et éventuellement du cache). Les fichiers `vector_db/*.pkl` sont soit versionnés, soit produits au build ; un utilisateur distant ne peut pas les modifier.
- **Recommandation :** Pour de futurs déploiements où des utilisateurs pourraient uploader ou modifier des données, remplacer le stockage par un format sans exécution (JSON, base vectorielle externe) au lieu de pickle.

---

## 4. Informations

### 4.1 Affichage de l’IP dans le bandeau

- L’app affiche l’IP du client (via api.ipify.org / icanhazip.com). C’est une information déjà connue du serveur ; l’impact est limité, mais cela peut être retiré si vous souhaitez limiter la surface d’information.

### 4.2 Pas d’authentification pour le contenu public

- Recherche, Agent et documents sont accessibles sans login. C’est cohérent pour des comptes rendus municipaux publics. Aucune mesure supplémentaire n’est nécessaire si ce modèle est voulu.

---

## 5. Bonnes pratiques déjà en place

- Secrets lus via `st.secrets` (pas de clés en dur dans le code pour la prod).
- Pas de `DEBUG` ou de clés Django exposées dans l’app Streamlit (Django est un autre front).
- Données sensibles (clé API, token admin) non présentes dans le dépôt actuel.
- Contenu utilisateur (recherche, réponses Agent) affiché via les widgets Streamlit (échappement par défaut).

---

## 6. Checklist post-scan

- [ ] Vérifier l’historique Git pour `.streamlit/secrets.toml` et révoquer les clés si besoin.
- [ ] Changer le token admin pour une valeur longue et aléatoire ; éviter de le mettre en URL si possible.
- [ ] Garder les secrets uniquement dans Streamlit Cloud (Settings → Secrets).
- [ ] Envisager un rate limiting sur l’endpoint Agent si le trafic augmente.
- [ ] Utiliser la validation des URLs des sources/PDF ajoutée dans `app.py` (voir correctif ci-dessous).

---

*Rapport généré par analyse statique du code et des configurations du dépôt.*
