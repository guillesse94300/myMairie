# myMairie — Recherche dans les Comptes Rendus du Conseil Municipal de Pierrefonds

Interface de recherche sémantique dans les comptes rendus du Conseil Municipal de Pierrefonds (2015–2026), basée sur une base vectorielle locale.

## Fonctionnalités

- **Recherche sémantique** — comprend le sens, pas seulement les mots exacts
- **Recherche exacte** — filtre les résultats contenant obligatoirement le(s) mot(s) cherché(s)
- **Filtres** par année (2015–2026)
- **Suggestions rapides** et thèmes prédéfinis (Forêt, Urbanisme, Budget, Voirie…)
- **Ouverture des PDFs** directement dans le navigateur
- **Score de pertinence** par résultat

## Prérequis

- Python 3.9+ (testé avec Python 3.14)
- Les fichiers PDF des comptes rendus dans le même dossier que `app.py`

## Installation et lancement

### Méthode simple (Windows)

Double-cliquer sur `startClaude.bat` — il installe les dépendances, indexe les PDFs et lance l'interface automatiquement.

### Méthode manuelle

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Indexer les PDFs (une seule fois, ~5-10 min)
python ingest.py

# 3. Lancer l'interface
streamlit run app.py
```

Ouvrir le navigateur sur : http://localhost:8501

## Structure du projet

```
myMairie/
├── app.py              # Interface Streamlit
├── ingest.py           # Indexation des PDFs
├── startClaude.bat     # Lancement Windows en un clic
├── requirements.txt    # Dépendances Python
├── README.md
├── vector_db/          # Base vectorielle (générée, non versionnée)
│   ├── embeddings.npy
│   ├── documents.pkl
│   └── metadata.pkl
└── *.pdf               # Comptes rendus (non versionnés)
```

## Technologies

| Composant | Technologie |
|---|---|
| Embeddings | `sentence-transformers` — modèle `paraphrase-multilingual-MiniLM-L12-v2` |
| Base vectorielle | `numpy` + `pickle` (cosine similarity) |
| Interface | `Streamlit` |
| Extraction PDF | `pdfplumber` |
| Serveur PDF | `http.server` (Python stdlib) |

## Remarques

- Les fichiers PDF et la base vectorielle (`vector_db/`) ne sont **pas** versionnés (trop volumineux).
- La première indexation télécharge le modèle d'embeddings (~90 Mo) et peut prendre 5 à 10 minutes.
- Relancer `ingest.py` après ajout de nouveaux PDFs.
