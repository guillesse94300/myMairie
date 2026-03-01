# Architecture technique du projet Casimir — Mairie Pierrefonds

Ce document décrit l’architecture du projet, les composants, le pipeline d’indexation et le déploiement.

---

## 1. Vue d’ensemble

Le projet comporte **deux frontends** et un **pipeline d’ingestion** commun :

| Composant | Rôle | Stack |
|-----------|------|--------|
| **Application principale** | Interface utilisateur (recherche, agent, stats, sources) | Streamlit, Plotly |
| **Application Django** | Recherche simple (alternative légère) | Django, `web/search` |
| **Pipeline d’indexation** | Alimentation de la base vectorielle et des stats | Python, `ingest.py`, `fetch_sites.py`, `stats_extract.py` |

La **base vectorielle** est construite par `ingest.py` et consommée par l’app Streamlit (et optionnellement par Django via une base au format `.npz`/`.json` distincte dans `build_vector_store.py`).

---

## 2. Structure des répertoires

```
Mairie/
├── app.py                    # Application Streamlit (Casimir)
├── ingest.py                 # Indexation .md + PDF → vector_db/
├── build_vector_store.py     # Base vectorielle alternative (Django, format .npz/.json)
├── fetch_sites.py            # Récupération URLs → knowledge_sites/*.md
├── copy_md_to_static.py      # Copie .md → static/ pour listing Sources
├── stats_extract.py          # Extraction stats PV → vector_db/stats.json
├── requirements.txt          # Dépendances Python
├── siteweb.txt / site_url.txt  # Liste d’URLs à scraper
├── deploy_date.txt           # Date de déploiement (écrit par deploy.bat)
├── static/                   # Fichiers statiques (PDF, .md copiés, Guide-utilisateurs.md)
│   └── journal/              # PDFs L’ECHO (copiés par ingest)
├── knowledge_sites/          # Fichiers .md issus de fetch_sites.py
├── journal/                  # PDFs L’ECHO (source) + download_calameo.py
├── vector_db/                # Base vectorielle (sortie de ingest.py)
│   ├── embeddings.npy        # Matrice (N, dim) float32 normalisée
│   ├── documents.pkl        # Liste de N textes (chunks)
│   ├── metadata.pkl         # Liste de N métadonnées (filename, date, year, chunk, …)
│   └── stats.json           # Stats séances/délibérations (sortie stats_extract.py)
├── docs/                     # Documentation
│   ├── Guide-utilisateurs.md
│   ├── Architecture-technique.md
│   └── Recherche-et-agent-RAG.md
├── web/                      # Application Django (recherche)
│   ├── config/               # Settings, urls
│   ├── search/               # App recherche (views, vector_search, templates)
│   └── manage.py
├── ALL.bat                   # Pipeline complet : URL → Guide → Update_Casimir → Deploy
├── URL.bat                   # fetch_sites.py (site_url.txt → knowledge_sites/)
├── Update_Casimir.bat        # ingest + copy_md + stats_extract
└── deploy.bat                # deploy_date, copy_md, git commit/push → Streamlit Cloud
```

---

## 3. Pipeline d’indexation

### 3.1 Script ALL.bat (pipeline complet)

Ordre d’exécution :

1. **URL** : `URL.bat` → lecture de `site_url.txt` (ou `siteweb.txt`), appel à `fetch_sites.py` → génération des `.md` dans `knowledge_sites/`.
2. **Guide utilisateur** : copie de `docs/Guide-utilisateurs.md` vers `static/Guide-utilisateurs.md` (pour la popup du site).
3. **Update_Casimir** : `Update_Casimir.bat` → `ingest.py --md-only`, puis optionnellement `ingest.py` (PDFs), `copy_md_to_static.py`, `stats_extract.py` si `vector_db/stats.json` absent.
4. **Deploy** : `deploy.bat` → mise à jour `deploy_date.txt`, `copy_md_to_static.py`, git add/commit/push → redéploiement Streamlit Cloud.

### 3.2 fetch_sites.py — Récupération des pages web

- **Entrée** : `site_url.txt` ou `siteweb.txt` (une URL par ligne).
- **Sortie** : un fichier `.md` par URL dans `knowledge_sites/`, avec en-tête `Source : <url>` et contenu texte extrait du HTML.

Stratégies de récupération (par ordre de priorité selon le domaine) :

- **Playwright** (headless Chromium) pour les domaines listés dans `JS_RENDER_DOMAINS` (ex. `notion.site`, `tripadvisor.fr`) : exécution du JavaScript, contournement anti-bot.
- **curl_cffi** (impersonation TLS Chrome) pour `TLS_IMPERSONATE_DOMAINS` (ex. `courrier-picard.fr`) : évite les 403.
- **requests** pour les autres URLs.
- **Fallback** : si échec (403, contenu vide), appel à ScraperAPI ou ZenRows si les variables d’environnement `SCRAPER_API_KEY` ou `ZENROWS_API_KEY` sont définies.

Les domaines dans `SKIP_DOMAINS` (ex. `facebook.com`) ne sont pas traités.

### 3.3 ingest.py — Indexation vers la base vectorielle

- **Entrée** :
  - Fichiers `.md` dans `knowledge_sites/` (toujours indexés en premier).
  - PDFs dans `static/` et `static/journal/` (si pas `--md-only`).
- **Sortie** : `vector_db/embeddings.npy`, `vector_db/documents.pkl`, `vector_db/metadata.pkl`.

Étapes :

1. **Copie des PDFs journal** : `journal/*.pdf` → `static/journal/` pour servir les PDFs côté Streamlit.
2. **Chargement du modèle** : `sentence-transformers` avec `paraphrase-multilingual-MiniLM-L12-v2` (CPU ou GPU si `USE_GPU` et CUDA).
3. **Traitement des .md** : lecture, extraction du contenu après `---`, découpage en chunks (voir document « Recherche et agent RAG »), métadonnées `filename` préfixé `[Web]`, `source_url` si présent.
4. **Traitement des PDFs** : extraction de texte avec `pdfplumber` ; pour les PDFs image (ex. L’ECHO), OCR via Tesseract puis EasyOCR en secours (activé par `INGEST_OCR_JOURNAL=1`). Découpage en chunks, extraction de la date depuis le nom de fichier (`extract_date`).
5. **Embeddings** : encodage par batch (64 textes), normalisation L2 pour similarité cosinus.
6. **Sauvegarde** : `np.save(embeddings.npy)`, `pickle.dump(documents.pkl)`, `pickle.dump(metadata.pkl)`.

Paramètres clés : `CHUNK_SIZE = 1000` (caractères), chunks de moins de 80 caractères exclus.

### 3.4 copy_md_to_static.py

Copie tous les `.md` de la racine (hors README) et de `knowledge_sites/` vers `static/` et `static/knowledge_sites/` pour que l’app Streamlit puisse les lister et les servir dans la section « Sources et Documents ».

### 3.5 stats_extract.py

Parcourt les PDFs dans `static/` (procès-verbaux), extrait avec `pdfplumber` et des regex :

- Date de séance, horaires (début/fin), durée.
- Liste des présents, absents, pouvoirs.
- Délibérations (titre, thème via `THEME_PATTERNS`, type de vote : unanimité / vote avec décompte, pour/contre/abstentions, noms).

Produit `vector_db/stats.json` utilisé par la section « Statistiques des séances » de l’app Streamlit.

---

## 4. Application Streamlit (app.py)

- **Page config** : `st.set_page_config(layout="wide", page_icon="🏛️")`.
- **État** : `st.session_state["current_section"]` = `home` | `agent` | `search` | `stats` | `docs`.
- **Ressources cachées** : `load_model()` et `load_db()` en `@st.cache_resource` (modèle SentenceTransformer, chargement de `vector_db/`).
- **Bandeau** : Accueil, À propos, Guide Utilisateur, email, date de déploiement, IP (via ipify), compteur de recherches et quota restant (rate limit).
- **Rate limiting** : 5 recherches/heure par IP (sauf whitelist `RATE_LIMIT_WHITELIST`), stockage en mémoire des timestamps par IP.
- **Mode admin** : `?admin=<token>` avec `ADMIN_TOKEN` dans `st.secrets` ; affichage d’infos supplémentaires (ex. nombre de passages indexés).

Fichiers statiques : les PDFs sont servis sous `app/static/` (Streamlit Cloud) ; les URLs sont générées via `_safe_pdf_url(rel_path)` pour éviter path traversal et schémas dangereux.

---

## 5. Application Django (web/)

- **Rôle** : interface de recherche alternative (formulaire + résultats), sans agent ni stats.
- **Base** : par défaut `BASE_VECTORIELLE` pointe vers `base_vectorielle/` (générée par `build_vector_store.py`), avec format `.npz` + `metadata.json` (structure différente de `ingest.py`). Pour utiliser la même base que Streamlit, il faudrait adapter `vector_search.py` pour lire `vector_db/embeddings.npy` + `documents.pkl` + `metadata.pkl`.
- **Recherche** : `vector_search.search()` avec seuils `MIN_SIMILARITY`, `MIN_SIMILARITY_IF_KEYWORD_MATCH`, filtre par mots-clés pour requêtes courtes.

---

## 6. Déploiement (deploy.bat)

1. Mise à jour de Streamlit (`pip install -U streamlit`).
2. Création du dossier `data/` si absent.
3. Écriture de la date dans `deploy_date.txt`.
4. Exécution de `copy_md_to_static.py`.
5. `git add -A`, commit (message demandé ou automatique), `git pull --rebase`, `git push origin main`.

Streamlit Cloud déploie automatiquement à partir du dépôt GitHub (branch `main`). Les secrets (ex. `GROQ_API_KEY`, `ADMIN_TOKEN`) sont à configurer dans le dashboard Streamlit Cloud.

---

## 7. Dépendances principales (requirements.txt)

- **Recherche / embeddings** : `sentence-transformers`, `numpy`.
- **Interface** : `streamlit`, `plotly`, `streamlit-javascript`.
- **Agent** : `groq`.
- **PDF** : `pdfplumber`, `PyMuPDF`, `Pillow`.
- **OCR** : `easyocr`, `pytesseract`.
- **Scraping** : `requests`, `beautifulsoup4`, `curl_cffi`, `playwright`.

Pour l’OCR des journaux, Tesseract peut être installé côté système (Windows : binaire Tesseract-OCR) ; sinon EasyOCR suffit (`pip install easyocr`). Pour Playwright : `playwright install chromium`.

---

## 8. Variables d’environnement et secrets

| Variable / secret | Usage |
|-------------------|--------|
| `INGEST_OCR_JOURNAL` | `1` pour activer l’OCR des PDFs L’ECHO dans `ingest.py`. |
| `USE_GPU` | Présent et CUDA disponible → modèle SentenceTransformer sur GPU. |
| `SCRAPER_API_KEY` / `ZENROWS_API_KEY` | Fallback scraping dans `fetch_sites.py` en cas d’échec direct. |
| `GROQ_API_KEY` (Streamlit secrets) | Appel API Groq pour l’agent (llama-3.3-70b-versatile). |
| `ADMIN_TOKEN` (Streamlit secrets) | Accès mode admin via `?admin=<token>`. |

---

*Documentation technique — projet Casimir, Mairie Pierrefonds.*
