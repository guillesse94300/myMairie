# Spécifications techniques : recherche sémantique et agent RAG

Ce document décrit les choix techniques de la recherche vectorielle, du chunking, de la recherche hybride pour l’agent et du pipeline RAG (Groq).

---

## 1. Modèle d’embeddings

- **Modèle** : `paraphrase-multilingual-MiniLM-L12-v2` (sentence-transformers).
- **Usage** : encodage des chunks à l’indexation et des requêtes à l’interrogation ; dimension de sortie fixe (384), multilingue (dont français).
- **Normalisation** : les vecteurs sont normalisés en L2 après encodage pour que le produit scalaire soit égal à la similarité cosinus.

---

## 2. Chunking (découpage des textes)

- **Taille** : `CHUNK_SIZE = 1000` caractères, `CHUNK_OVERLAP = 180` (définis dans `ingest.py`).
- **Règle** : découpage par paragraphes (splits sur `\n`), accumulation de paragraphes jusqu’à dépassement de la taille ; les chunks de moins de 80 caractères sont ignorés.
- **Overlap** : recouvrement de 180 caractères entre chunks pour ne pas couper tableaux et barèmes.

Pour les fichiers `.md`, le contenu après le premier `---` est seul utilisé pour éviter d’indexer le front matter.

---

## 3. Stockage de la base vectorielle (Streamlit / ingest)

- **embeddings.npy** : tableau NumPy `float32`, forme `(N, 384)`, lignes déjà normalisées (norme L2 = 1).
- **documents.pkl** : liste Python de N chaînes (texte de chaque chunk).
- **metadata.pkl** : liste de N dictionnaires ; clés typiques : `filename`, `rel_path`, `date`, `year`, `chunk`, `total_chunks`, et optionnellement `source_url` pour les sources web.

Alignement : l’index `i` correspond à la i‑ème ligne de `embeddings.npy`, au i‑ème élément de `documents.pkl` et au i‑ème élément de `metadata.pkl`.

---

## 4. Recherche sémantique (app.py)

### 4.1 Fonction `search()`

- Encodage de la requête avec le même modèle, puis normalisation L2.
- **Score** : `scores = embeddings @ q_emb` (produit matrice–vecteur = similarité cosinus par chunk).
- **Filtres optionnels** :
  - **year_filter** : ne garde que les métadonnées dont `year` est dans la liste fournie ; les autres reçoivent un score forcé à -1.
  - **exact** : si `True`, seuls les chunks contenant au moins un mot de la requête (termes de plus de 2 caractères) conservent leur score ; les autres passent à -1.
- Tri par score décroissant et retour des `n` premiers résultats `(document, metadata, score)`.

### 4.2 Recherche hybride pour l’agent : `search_agent()`

Objectif : combiner sémantique et présence de termes importants, puis élargir le contexte avec les chunks voisins du même fichier.

1. **Recherche sémantique** : appel à `search(question, ..., exact=False)` → premiers candidats.
2. **Mots significatifs** : extraction des mots de la question (≥ 4 caractères, hors liste de stop words français `_STOP_FR`).
3. **Recherche exacte** : si des mots significatifs existent, appel à `search(focused_query, ..., exact=True)` avec ces mots ; bonus de +0,05 au score pour les chunks retenus.
4. **Bonus chiffres** : si la question contient des mots liés aux tarifs/montants (tarif, barème, prix, quotient, etc.), les chunks contenant au moins un chiffre reçoivent un bonus de +0,04 pour favoriser les passages avec barèmes.
5. **Fusion** : union des résultats par clé `(filename, chunk)` ; en cas de doublon, conservation du meilleur score.
6. **Expansion de contexte** : pour chaque chunk retenu, ajout des chunks voisins du même fichier (chunk ± 1 et ± 2) avec un score dégressif (score − 0,05 × |delta|).
7. Tri par score décroissant et retour des `n` premiers résultats (scores plafonnés à 1,0).

Cela permet d’inclure des délibérations ou paragraphes adjacents pour améliorer la cohérence de la réponse du LLM.

---

## 5. Agent RAG (Casimir)

### 5.1 Flux

1. L’utilisateur envoie une question.
2. **Rate limit** : vérification 5 requêtes/heure par IP (sauf whitelist) ; si dépassé, message d’erreur et pas d’appel API.
3. **Récupération des passages** : `search_agent(question, ...)` avec `n=22` et filtre année optionnel.
4. **Construction du contexte** : les passages sont formatés en XML avec balises `<source id="i" fichier="...">...</source>` et envoyés au LLM.
5. **Appel LLM** : API Groq, modèle `llama-3.3-70b-versatile`, streaming des tokens ; prompt système fixe + message utilisateur (question + contexte).
6. **Post-traitement** : les références `[N]` dans la réponse sont remplacées par des liens Markdown vers le PDF ou l’URL source ; suppression des balises `<source>` résiduelles.

### 5.2 Prompt système (SYSTEM_AGENT)

- Rôle : assistant spécialisé sur les procès-verbaux du Conseil municipal de Pierrefonds.
- Contenu : contexte municipal (élus, commissions, intercommunalité, équipements, géographie, actualités), puis **règles strictes** :
  - Répondre uniquement à partir des passages fournis entre `<source>`.
  - Ne pas citer de montant/chiffre non explicitement associé au sujet dans le passage.
  - En l’absence d’information : le dire clairement ; pour les montants, indiquer où les trouver (PV sur mairie-pierrefonds.fr).
  - Réponse en français, concise, structurée.
  - Citer les sources par numéro entre crochets, ex. `[1]`, `[3]`.
  - Ne jamais réécrire les balises `<source>` dans la réponse.
  - Le contexte municipal sert à comprendre acronymes et acteurs, pas à inventer des faits.

### 5.3 API Groq

- **Modèle** : `llama-3.3-70b-versatile`.
- **Paramètres** : `max_tokens=1500`, `stream=True`.
- **Clé** : lue depuis `st.secrets.get("GROQ_API_KEY")` ; si absente, message d’erreur invitant à configurer la clé (ex. dans `.streamlit/secrets.toml` en local).

### 5.4 Post-traitement des liens sources (`_liens_sources()`)

- Construction d’un mapping `id (1-based) → (filename, url, icon)` à partir des passages : si `source_url` est une URL http(s), lien externe (icône 🌐) ; sinon lien vers PDF via `_safe_pdf_url(rel_path)` (icône 📄).
- Dans le texte de la réponse :
  - Remplacement des `[N]` (références du LLM) par des liens Markdown `[icon label](url)`.
  - Suppression des balises `<source ...>` et `</source>` résiduelles.
- `_safe_pdf_url` et `_safe_source_url` garantissent l’absence de path traversal et de schémas dangereux (javascript:, data:, etc.).

---

## 6. Rate limiting

- **Limite** : 5 recherches par heure et par IP (constantes `RATE_LIMIT_MAX`, `RATE_LIMIT_WINDOW`).
- **Stockage** : dictionnaire en mémoire `_rate_limit_store` : IP → liste des timestamps des requêtes ; fenêtre glissante (suppression des timestamps hors fenêtre).
- **Whitelist** : les IP dans `RATE_LIMIT_WHITELIST` ne sont pas limitées (et n’affichent pas de « restant »).
- **Comptage** : chaque recherche (agent ou recherche sémantique) consomme 1 crédit ; `rate_limit_check_and_consume()` vérifie et enregistre ; `rate_limit_get_remaining()` retourne le nombre restant sans consommer.
- **Affichage** : dans le bandeau, nombre de recherches « aujourd’hui » (depuis minuit) et « vous » (reste sur la fenêtre d’1 h).

---

## 7. Statistiques (section « Statistiques des séances »)

- **Source** : `vector_db/stats.json` produit par `stats_extract.py`.
- **Contenu** : liste de séances avec `annee`, `date`, `nb_deliberations`, `deliberations` (titre, thème, vote), `presences`, `duree_minutes`, etc.
- **Filtre** : l’utilisateur peut restreindre par année(s) via un multiselect.
- **Graphiques** (Plotly) : délibérations et séances par année (barres), répartition des types de vote (camembert), durée moyenne par année et durée par séance (barres / scatter), présences des conseillers (barres horizontales), thèmes des délibérations (camembert), liste des votes avec opposition ou abstention (expandables).

---

## 8. Sécurité et bonnes pratiques

- **URLs et chemins** : `_safe_pdf_url(rel_path)` interdit `..`, `/` en tête et schémas dangereux ; `_safe_source_url(url)` n’accepte que `http://` et `https://`.
- **Secrets** : pas de clé API en dur ; lecture via `st.secrets` (Streamlit Cloud) ou `.streamlit/secrets.toml` en local.
- **Admin** : accès réservé via `?admin=<ADMIN_TOKEN>` ; le token est comparé à `st.secrets.get("ADMIN_TOKEN")`.

---

*Documentation technique — recherche et agent RAG, projet Casimir, Mairie Pierrefonds.*
