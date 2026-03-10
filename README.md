# Casimir — Assistant IA de la Mairie de Pierrefonds

Interface de recherche sémantique (RAG) dans les documents municipaux de Pierrefonds (Oise) :
procès-verbaux du Conseil Municipal (2015–2026), journaux municipaux, documents intercommunaux,
ressources touristiques et patrimoniales.

**Application en ligne :** [mymairie.streamlit.app](https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app)

---

## Architecture — Pipeline en 4 phases

```
Acquire.bat  →  Transform.bat  →  Ingest.bat  →  deploy.bat
  Phase 1          Phase 2          Phase 3         Phase 4
  source/          input/           vector_db/      GitHub → Streamlit Cloud
```

---

## Phase 1 — Acquisition

### `Acquire.bat` ← point d'entrée

Menu interactif :

```
1. Sites web   → acquire.py              → source/  (images, pdf, md)
2. Oise Mag.   → download_oise_magazines → source/pdf/
3. Digipad     → download_digipad        → source/pdf/
4. PDF Search  → google_pdf_download     → source/pdf/  (DuckDuckGo)
5. Tout        → enchaîne 1 + 2 + 3 + 4
```

### Scripts Python

| Script | Rôle | Sortie |
|---|---|---|
| `acquire.py` | Lit `site_url.txt`, télécharge chaque URL (Wikipedia, Calameo, sites JS-heavy via Playwright) | `source/images/`, `source/pdf/`, `source/md/` |
| `download_oise_magazines.py` | Magazines Oise n°1→38 depuis oise.fr · `-o` pour changer le dossier | `source/pdf/` |
| `download_digipad.py` | 19 fiches pédagogiques Château de Pierrefonds (S3 Digipad) · `-o` pour changer le dossier | `source/pdf/` |
| `google_pdf_download.py` | Recherche DuckDuckGo + téléchargement PDFs trouvés · mode interactif ou `python google_pdf_download.py termes -o dossier` | `source/pdf/` |

### Fichier de configuration

`site_url.txt` — une URL par ligne, `#` pour les commentaires.

---

## Phase 2 — Transformation

### `Transform.bat` ← point d'entrée

Menu interactif avec options modificateurs :

```
1. Images    → source/images/          → input/  (OCR Tesseract/EasyOCR)
2. Markdown  → source/md/ + static/   → input/  (nettoyage)
3. PDFs      → source/pdf/ + static/  → input/  (extraction texte ou OCR)
4. Tout      → 1 + 2 + 3
F. Active --force     (retraite même les fichiers déjà en cache)
S. Active --no-static (ignore les fichiers de static/)
```

Les logs sont horodatés dans `logs/transform_YYYYMMDD_HHmm.log`.

### Script Python

| Script | Rôle |
|---|---|
| `transform.py` | Convertit tous les artefacts bruts de `source/` et les PDFs de `static/` en fichiers `.md` propres dans `input/`. Système de cache (ne retraite pas si déjà à jour). OCR si nécessaire. |

---

## Phase 3 — Indexation

### `Ingest.bat` ← point d'entrée (installe aussi les dépendances)

Enchaîne automatiquement :
1. `pip install -r requirements.txt`
2. `playwright install chromium`
3. Vérification/installation de Tesseract OCR (packs langue fra + eng)
4. `python ingest.py` (tous les arguments passés au bat sont transmis)

### `update_casimir.bat` ← raccourci rapide (sans réinstallation)

```
ingest.py --md-dir input/ --md-only  →  vector_db/
stats_extract.py                     →  vector_db/stats.json
git commit + push vector_db/  (optionnel)
```

### Scripts Python

| Script | Rôle | Sortie |
|---|---|---|
| `ingest.py` | Indexeur principal. Découpe les `.md` en chunks, génère les embeddings (`paraphrase-multilingual-MiniLM-L12-v2`), indexe aussi les tableaux PDF. OCR pour PDFs image (L'Écho). `--md-only` pour n'indexer que les `.md`. | `vector_db/` |
| `stats_extract.py` | Extrait les statistiques de vote des PV du Conseil Municipal (thèmes, horaires, résultats) | `vector_db/stats.json` |

---

## Phase 4 — Déploiement

### `deploy.bat`

```
pip install -U streamlit
git add -A  +  force-add vector_db/
git commit  (message horodaté automatique)
git pull --rebase  +  git push origin main
→ Streamlit Cloud se redéploie automatiquement
```

---

## Interface utilisateur

### `app.py` — Application Streamlit "Casimir"

- **Recherche hybride** : embeddings (similarité sémantique) + BM25 (mots-clés)
- **LLM** : Groq API — llama-3.3-70b-versatile
- **Filtres** : année, type de document
- **Statistiques** de vote des délibérations (graphiques Plotly)
- **Ouverture des PDFs** directement dans le navigateur
- Clé API dans `.streamlit/secrets.toml` (`GROQ_API_KEY`)

---

## Utilitaires

| Script | Rôle |
|---|---|
| `query_vector_store.py` | Interroge la base vectorielle en ligne de commande (mode interactif ou argument direct) |
| `search_pdf.py` | Recherche de termes précis (Haucourt, Vertefeuille, VTT…) dans les PDFs |
| `creer_resume_comptes_rendus.py` | Génère un `.docx` résumant thématiquement les comptes rendus du CM |
| `creer_resume_word.py` | Génère un `.docx` avec les extraits PDF contenant des termes recherchés |
| `generate_baseline_answers.py` | Génère les réponses de référence de Casimir → `tests/baseline_agent_examples.json` |
| `copy_md_to_static.py` | Copie les `.md` de `knowledge_sites/` vers `static/` pour l'interface |
| `scripts/dvf_pierrefonds_csv.py` | Filtre les données DVF (DGFiP) pour ne garder que Pierrefonds → CSV/Excel |
| `dump.bat` | Exporte les recherches utilisateurs depuis l'app déployée (via token admin) |
| `TEST.bat` | Lance `pytest tests/test_casimir_agent_examples.py` |

---

## Structure des répertoires

```
myMairie/
├── site_url.txt          # URLs à acquérir (une par ligne, # = commentaire)
├── source/               # Artefacts bruts téléchargés
│   ├── images/{stem}/    # Captures d'écran Playwright / thumbnails
│   ├── pdf/{stem}.pdf    # PDFs téléchargés directement
│   └── md/{stem}.md      # Texte extrait (Wikipedia, sites génériques)
├── static/               # PDFs servis par Streamlit (PV mairie, L'Écho…)
├── input/                # .md propres prêts pour l'indexation
├── vector_db/            # Base vectorielle (versionnée)
│   ├── embeddings.npy
│   ├── documents.pkl
│   ├── metadata.pkl
│   └── stats.json
├── fetcher/              # Module Python d'acquisition (dispatcher, fetchers)
├── logs/                 # Logs horodatés de Transform.bat
├── tests/                # Tests pytest + baseline Casimir
└── docs/                 # Guide utilisateur, Architecture technique
```

---

## Technologies

| Composant | Technologie |
|---|---|
| Embeddings | `sentence-transformers` — `paraphrase-multilingual-MiniLM-L12-v2` |
| Recherche hybride | `numpy` cosine similarity + `rank_bm25` |
| LLM | Groq API — llama-3.3-70b-versatile |
| Interface | Streamlit |
| Extraction PDF | `pdfplumber` + `pypdf` |
| OCR | Tesseract (prioritaire) ou EasyOCR (fallback) |
| Scraping JS | Playwright (chromium headless) |
| Anti-bot | `curl_cffi` (imitation TLS Chrome) |

---

## Démarrage rapide

```bash
# 1. Acquérir les documents
Acquire.bat          # menu interactif

# 2. Transformer en .md
Transform.bat        # menu interactif

# 3. Indexer
Ingest.bat           # installe dépendances + indexe
# ou, si déjà installé :
update_casimir.bat

# 4. Lancer localement
streamlit run app.py

# 5. Déployer
deploy.bat
```
