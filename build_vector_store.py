# -*- coding: utf-8 -*-
"""
Construit une base vectorielle à partir de tous les PDF du dossier.
Embeddings avec sentence-transformers (local). Stockage en .npz + .json (pas de ChromaDB).
"""
import re
import json
from pathlib import Path
from pypdf import PdfReader
import numpy as np
from sentence_transformers import SentenceTransformer

DOSSIER = Path(__file__).resolve().parent
STORE_DIR = DOSSIER / "base_vectorielle"
EMBEDDINGS_FILE = STORE_DIR / "embeddings.npz"
META_FILE = STORE_DIR / "metadata.json"

CHUNK_SIZE = 600
CHUNK_OVERLAP = 150
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def nettoyer_texte(s):
    if not s or not s.strip():
        return ""
    return " ".join(s.split()).strip()


def decouper_paragraphes(texte):
    if not texte.strip():
        return []
    blocs = re.split(r"\n\s*\n", texte)
    resultats = []
    for bloc in blocs:
        bloc = nettoyer_texte(bloc)
        if len(bloc) <= CHUNK_SIZE:
            if len(bloc) >= 50:
                resultats.append(bloc)
        else:
            start = 0
            while start < len(bloc):
                fin = start + CHUNK_SIZE
                chunk = bloc[start:fin]
                if len(chunk) >= 50:
                    resultats.append(chunk)
                start = fin - CHUNK_OVERLAP
    return resultats


def main():
    STORE_DIR.mkdir(exist_ok=True)

    print("Chargement du modèle d'embeddings...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    pdfs = sorted(p for p in DOSSIER.glob("*.pdf") if p.is_file())
    all_docs = []
    all_metadatas = []

    for i, path in enumerate(pdfs, 1):
        print(f"Traitement ({i}/{len(pdfs)}): {path.name}")
        try:
            reader = PdfReader(str(path))
            for num_page, page in enumerate(reader.pages, start=1):
                texte = page.extract_text() or ""
                chunks = decouper_paragraphes(texte)
                for chunk in chunks:
                    all_docs.append(chunk)
                    all_metadatas.append({
                        "fichier": path.name,
                        "page": num_page,
                        "source": f"{path.name} (page {num_page})",
                    })
        except Exception as e:
            print(f"  Erreur: {e}")

    if not all_docs:
        print("Aucun document à indexer.")
        return

    print(f"Génération des embeddings pour {len(all_docs)} segments...")
    embeddings = model.encode(all_docs, show_progress_bar=True)
    embeddings = np.array(embeddings, dtype=np.float32)

    np.savez_compressed(
        EMBEDDINGS_FILE,
        embeddings=embeddings,
    )
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump({"documents": all_docs, "metadatas": all_metadatas}, f, ensure_ascii=False, indent=0)

    print(f"\nBase vectorielle créée : {STORE_DIR}")
    print(f"  - {EMBEDDINGS_FILE.name}")
    print(f"  - {META_FILE.name}")
    print(f"Segments indexés : {len(all_docs)}")


if __name__ == "__main__":
    main()
