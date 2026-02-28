"""
ingest.py — Indexe tous les PDFs du Conseil Municipal + journal (L'ECHO)
Stockage : embeddings.npy + metadata.pkl + documents.pkl
Usage    : python ingest.py

Pour les PDFs image (ex. L'ECHO), utilise l'OCR :
- Tesseract si installé (https://github.com/UB-Mannheim/tesseract/wiki)
- Sinon EasyOCR (pip install easyocr) — pas de binaire externe
"""

import re
import warnings

# Supprimer le warning PyTorch "pin_memory" sur machine sans GPU
warnings.filterwarnings("ignore", message=".*pin_memory.*", category=UserWarning)
import shutil
import pickle
import sys
import pdfplumber
import numpy as np
from sentence_transformers import SentenceTransformer
from pathlib import Path

# OCR pour PDFs image (L'ECHO) — Tesseract puis EasyOCR en secours
_OCR_TESSERACT = False
_OCR_EASYOCR = False
_easyocr_reader = None

try:
    import fitz  # PyMuPDF
    from PIL import Image
    import pytesseract
    if sys.platform == "win32":
        for path in [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]:
            if Path(path).exists():
                pytesseract.pytesseract.tesseract_cmd = path
                break
    try:
        pytesseract.get_tesseract_version()
        _OCR_TESSERACT = True
    except Exception:
        pass
except ImportError:
    pass

if not _OCR_TESSERACT:
    try:
        import easyocr
        _OCR_EASYOCR = True
    except ImportError:
        pass

_OCR_AVAILABLE = _OCR_TESSERACT or _OCR_EASYOCR

# ── Configuration ──────────────────────────────────────────────────────────────
APP_DIR        = Path(__file__).parent
STATIC_DIR     = APP_DIR / "static"
JOURNAL_DIR    = APP_DIR / "journal"
KNOWLEDGE_DIR  = APP_DIR / "knowledge_sites"  # .md issus de fetch_sites.py
DB_DIR         = APP_DIR / "vector_db"
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

    # LECHO-NN-mois-YYYY  ex: LECHO-01-decembre-2020, LECHO-12-avril-2025
    m = re.search(r"lecho-\d+-(\w+)-(\d{4})", name)
    if m:
        mon = m.group(1).lower().replace("é", "e").replace("è", "e").replace("û", "u").replace("à", "a")
        if mon in MONTHS_FR:
            return f"{m.group(2)}-{MONTHS_FR[mon]}-01", m.group(2)

    return "0000-00-00", "0000"


# ── OCR pour PDFs image (L'ECHO) ───────────────────────────────────────────────
def _ocr_tesseract(doc) -> list:
    """OCR via Tesseract."""
    pages_text = []
    for page in doc:
        pix = page.get_pixmap(dpi=200, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img, lang="fra+eng")
        if text.strip():
            pages_text.append(text.strip())
    return pages_text


def _ocr_easyocr(doc) -> list:
    """OCR via EasyOCR (fallback, pas de binaire externe)."""
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["fr", "en"], gpu=False, verbose=False)
    pages_text = []
    for page in doc:
        pix = page.get_pixmap(dpi=200, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        result = _easyocr_reader.readtext(arr)
        text = " ".join(r[1] for r in result if r[1].strip())
        if text.strip():
            pages_text.append(text.strip())
    return pages_text


def extract_text_ocr(pdf_path: Path) -> list:
    """
    Extrait le texte d'un PDF image via OCR.
    Essaie Tesseract puis EasyOCR en secours.
    """
    if not _OCR_AVAILABLE:
        return []
    try:
        doc = fitz.open(pdf_path)
        pages_text = []
        if _OCR_TESSERACT:
            try:
                pages_text = _ocr_tesseract(doc)
            except Exception:
                pass
        if not pages_text and _OCR_EASYOCR:
            doc.close()
            doc = fitz.open(pdf_path)
            pages_text = _ocr_easyocr(doc)
        doc.close()
        return pages_text
    except Exception:
        return []


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
def _check_ocr() -> bool:
    """Vérifie qu'au moins un OCR est disponible."""
    if _OCR_AVAILABLE:
        return True
    print(
        "\n  [!] Pour l'OCR des PDFs L'ECHO (image), installez :\n"
        "      pip install easyocr   (recommandé, pas de binaire externe)\n"
        "      ou Tesseract : https://github.com/UB-Mannheim/tesseract/wiki\n"
    )
    return False


def main():
    DB_DIR.mkdir(exist_ok=True)

    _ocr_ok = _check_ocr()

    # Copier les PDFs du journal vers static/journal/ pour que Streamlit puisse les servir
    static_journal = STATIC_DIR / "journal"
    if JOURNAL_DIR.exists():
        static_journal.mkdir(parents=True, exist_ok=True)
        for pdf in JOURNAL_DIR.glob("*.pdf"):
            dest = static_journal / pdf.name
            if not dest.exists() or pdf.stat().st_mtime > dest.stat().st_mtime:
                shutil.copy2(pdf, dest)
                print(f"  Copie : journal/{pdf.name} -> static/journal/")

    print(f"Chargement du modele '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)

    # Collecter tous les PDFs : static/ (récursif, inclut static/journal/)
    pdf_files = []
    if STATIC_DIR.exists():
        for p in sorted(STATIC_DIR.rglob("*.pdf")):
            if p.is_file():
                pdf_files.append(p)
    print(f"{len(pdf_files)} fichiers PDF trouves (static + journal).\n")

    all_docs, all_metadatas = [], []
    skipped = []

    for pdf_path in pdf_files:
        date_iso, year = extract_date(pdf_path.name)
        # rel_path : pour l'URL Streamlit (app/static/...)
        if "journal" in str(pdf_path).replace("\\", "/"):
            rel_path = f"journal/{pdf_path.name}"
        else:
            rel_path = pdf_path.name
        print(f"  [{date_iso}] {pdf_path.name}", end=" ... ")

        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_text = [p.extract_text() for p in pdf.pages if p.extract_text()]

            # Si aucun texte (PDF image type L'ECHO), tenter l'OCR
            if not pages_text and _OCR_AVAILABLE:
                pages_text = extract_text_ocr(pdf_path)
                if pages_text:
                    print("OCR", end=" ... ")

            if not pages_text:
                if not _OCR_AVAILABLE:
                    print("aucun texte (PDF scanne ? pip install easyocr pour l'OCR)")
                else:
                    print("aucun texte (OCR echoue ?)")
                skipped.append(pdf_path.name)
                continue

            full_text = "\n".join(pages_text)
            chunks = chunk_text(full_text)
            if not chunks and len(full_text) > 80:
                chunks = [full_text]
            print(f"{len(chunks)} chunks")

            for i, chunk in enumerate(chunks):
                all_docs.append(chunk)
                all_metadatas.append({
                    "filename": pdf_path.name,
                    "rel_path": rel_path,
                    "date": date_iso,
                    "year": year,
                    "chunk": i,
                    "total_chunks": len(chunks),
                })

        except Exception as e:
            print(f"ERREUR : {e}")
            skipped.append(pdf_path.name)

    # ── Fichiers .md (connaissance web) ─────────────────────────────────────────
    if KNOWLEDGE_DIR.exists():
        md_files = sorted(KNOWLEDGE_DIR.glob("*.md"))
        if md_files:
            print(f"\n{len(md_files)} fichier(s) .md (sites web) trouve(s).\n")
        for md_path in md_files:
            try:
                raw = md_path.read_text(encoding="utf-8")
                # Extraire source_url depuis "Source : URL" en début de fichier
                source_url = ""
                for line in raw.split("\n")[:10]:
                    if line.strip().lower().startswith("source :"):
                        source_url = line.split(":", 1)[-1].strip()
                        break
                # Ignorer l'en-tête (titre + source + ---) pour le contenu
                if "---" in raw:
                    content = raw.split("---", 1)[-1].strip()
                else:
                    content = raw
                chunks = chunk_text(content)
                if not chunks and len(content) > 80:
                    chunks = [content]
                if not chunks:
                    skipped.append(md_path.name)
                    continue
                label = f"[Web] {md_path.stem}"
                print(f"  [web] {md_path.name} -> {len(chunks)} chunks")
                for i, chunk in enumerate(chunks):
                    all_docs.append(chunk)
                    meta = {
                        "filename": label,
                        "rel_path": source_url or md_path.name,
                        "date": "web",
                        "year": "web",
                        "chunk": i,
                        "total_chunks": len(chunks),
                    }
                    if source_url:
                        meta["source_url"] = source_url
                    all_metadatas.append(meta)
            except Exception as e:
                print(f"  ERREUR {md_path.name} : {e}")
                skipped.append(md_path.name)

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
