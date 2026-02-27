"""
ingest.py — Indexe tous les PDFs du Conseil Municipal
Stockage : embeddings.npy + metadata.pkl + documents.pkl
Usage    : python ingest.py
"""

import re
import pickle
import pdfplumber
import numpy as np
from sentence_transformers import SentenceTransformer
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
PDF_DIR        = Path(__file__).parent
DB_DIR         = PDF_DIR / "vector_db"
MODEL_NAME     = "paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE     = 1000   # caractères max par chunk

# ── Extraction de la date depuis le nom de fichier ─────────────────────────────
MONTHS_FR = {
    "janvier": "01", "fevrier": "02", "mars": "03", "avril": "04",
    "mai": "05", "juin": "06", "juillet": "07", "aout": "08",
    "septembre": "09", "octobre": "10", "novembre": "11", "decembre": "12"
}

def extract_date(filename: str) -> tuple:
    """Retourne (date ISO 'YYYY-MM-DD', année 'YYYY')."""
    name = filename.lower().replace(".pdf", "")

    # YYYYMMDD  ex: 20241015-PV
    m = re.search(r"(\d{8})", name)
    if m:
        d = m.group(1)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}", d[:4]

    # DD-MM-YYYY  ex: compte-rendu-15-10-2015
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", name)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}", m.group(3)

    # DD-MOIS-YYYY  ex: CM-13-JANVIER-2022
    year_m = re.search(r"(\d{4})", name)
    year = year_m.group(1) if year_m else "0000"
    for month_name, month_num in MONTHS_FR.items():
        if month_name in name:
            day_m = re.search(r"(\d{1,2})-" + month_name, name)
            day = day_m.group(1).zfill(2) if day_m else "01"
            return f"{year}-{month_num}-{day}", year

    return "0000-00-00", "0000"


# ── Découpage du texte en chunks ───────────────────────────────────────────────
def chunk_text(text: str, size: int = CHUNK_SIZE) -> list:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 1 > size and current:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + " " + para).strip() if current else para
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 80]


# ── Programme principal ────────────────────────────────────────────────────────
def main():
    DB_DIR.mkdir(exist_ok=True)

    print(f"Chargement du modele '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    print(f"{len(pdf_files)} fichiers PDF trouves.\n")

    all_docs, all_metadatas = [], []
    skipped = []

    for pdf_path in pdf_files:
        date_iso, year = extract_date(pdf_path.name)
        print(f"  [{date_iso}] {pdf_path.name}", end=" ... ")

        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_text = [p.extract_text() for p in pdf.pages if p.extract_text()]

            if not pages_text:
                print("aucun texte (PDF scanne ?)")
                skipped.append(pdf_path.name)
                continue

            chunks = chunk_text("\n".join(pages_text))
            print(f"{len(chunks)} chunks")

            for i, chunk in enumerate(chunks):
                all_docs.append(chunk)
                all_metadatas.append({
                    "filename": pdf_path.name,
                    "date": date_iso,
                    "year": year,
                    "chunk": i,
                    "total_chunks": len(chunks),
                })

        except Exception as e:
            print(f"ERREUR : {e}")
            skipped.append(pdf_path.name)

    # Génération des embeddings
    print(f"\nGeneration de {len(all_docs)} embeddings...")
    BATCH = 64
    all_embeddings = []
    for i in range(0, len(all_docs), BATCH):
        batch = all_docs[i : i + BATCH]
        embs = model.encode(batch, show_progress_bar=False)
        all_embeddings.extend(embs.tolist())
        print(f"  {min(i + BATCH, len(all_docs))}/{len(all_docs)}", end="\r")
    print()

    # Normalisation pour cosine similarity via produit scalaire
    emb_array = np.array(all_embeddings, dtype=np.float32)
    norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
    emb_array = emb_array / np.maximum(norms, 1e-9)

    # Sauvegarde
    np.save(DB_DIR / "embeddings.npy", emb_array)
    with open(DB_DIR / "documents.pkl", "wb") as f:
        pickle.dump(all_docs, f)
    with open(DB_DIR / "metadata.pkl", "wb") as f:
        pickle.dump(all_metadatas, f)

    print(f"\n Indexation terminee : {len(all_docs)} chunks sauvegardes dans '{DB_DIR}'.")
    if skipped:
        print(f"Fichiers ignores ({len(skipped)}) :")
        for f in skipped:
            print(f"   - {f}")


if __name__ == "__main__":
    main()
