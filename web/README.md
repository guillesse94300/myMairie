# Recherche documents Mairie – Interface web

Interface Django pour interroger la base vectorielle des PDF (PV, comptes-rendus).

## Prérequis

- Base vectorielle déjà construite : depuis le dossier **Mairie** (parent de `web/`), exécuter :
  ```bash
  python build_vector_store.py
  ```

## Lancer l’application

Depuis ce dossier (`web/`) :

```bash
pip install -r requirements.txt
python manage.py runserver 8000
```

Puis ouvrir : **http://127.0.0.1:8000/**

La première recherche peut prendre quelques secondes (chargement du modèle d’embeddings).

## Structure

- `config/` – réglages Django, URLs
- `search/` – application de recherche
  - `vector_search.py` – chargement de la base et requêtes
  - `views.py` – page d’accueil et formulaire
  - `templates/search/index.html` – formulaire + résultats
