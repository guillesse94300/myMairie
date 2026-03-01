"""
ingest.py — Indexe d'abord les .md (sites web), puis optionnellement les PDFs (PV, L'ECHO)
Stockage : embeddings.npy + metadata.pkl + documents.pkl
Usage    : python ingest.py           # .md puis PDFs
           python ingest.py --md-only # uniquement .md (sites web)

- Tableaux PDF : extraction des tableaux (barèmes, tarifs cantine/périscolaire) via pdfplumber
  extract_tables(), en plus du texte ; chaque tableau est aussi indexé comme chunk dédié.

Pour les PDFs image (ex. L'ECHO), utilise l'OCR :
- Tesseract si installé (https://github.com/UB-Mannheim/tesseract/wiki)
- Sinon EasyOCR (pip install easyocr) — pas de binaire externe
"""

import argparse
import os
import re
import warnings

# Supprimer les warnings non bloquants (pin_memory, HF Hub)
warnings.filterwarnings("ignore", message=".*pin_memory.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*HF_TOKEN.*", category=UserWarning)
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
CHUNK_OVERLAP  = 180    # recouvrement entre chunks (évite de couper tableaux/chiffres)

# OCR des PDFs journal (L'ECHO) : très lent en CPU. Mettre INGEST_OCR_JOURNAL=1 pour l'activer.
OCR_JOURNAL    = os.environ.get("INGEST_OCR_JOURNAL", "0").strip().lower() in ("1", "true", "yes")

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
    """OCR via EasyOCR (fallback, pas de binaire externe). Une page en erreur est ignorée."""
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["fr", "en"], gpu=False, verbose=False)
    pages_text = []
    for page in doc:
        try:
            pix = page.get_pixmap(dpi=200, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            result = _easyocr_reader.readtext(arr)
            text = " ".join(r[1] for r in result if r[1].strip())
            if text.strip():
                pages_text.append(text.strip())
        except Exception:
            # Une page qui fait planter EasyOCR est ignorée (ex. format particulier)
            continue
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


# ── Conversion des tableaux PDF en texte (barèmes, tarifs cantine/périscolaire) ─
def _table_to_text(table: list) -> str:
    """Convertit un tableau pdfplumber (liste de listes) en texte lisible pour l'indexation."""
    if not table:
        return ""
    lines = []
    for row in table:
        cells = [str(c).strip() if c is not None else "" for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines) if lines else ""


def _extract_page_text_and_tables(page):
    """
    Extrait le texte d'une page PDF et y ajoute le contenu des tableaux détectés.
    Retourne (texte_complet, liste_des_texte_tableaux) pour permettre d'indexer
    aussi chaque tableau comme chunk dédié (meilleure recherche tarifs/barèmes).
    """
    text = page.extract_text() or ""
    table_texts = []
    try:
        tables = page.extract_tables() or []
    except Exception:
        tables = []
    for tbl in tables:
        if not tbl:
            continue
        table_text = _table_to_text(tbl)
        if table_text.strip():
            text += "\n\n[Tableau]\n" + table_text
            # Chunks dédiés aux tableaux pour améliorer la recherche "tarif cantine", "barème"
            table_texts.append(table_text)
    return text.strip(), table_texts


# ── Découpage du texte en chunks (avec overlap pour préserver tableaux/chiffres) ─
def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 1 > size and current:
            chunks.append(current.strip())
            # Garder un recouvrement : repartir de la fin du chunk pour ne pas couper barèmes/tarifs
            if overlap > 0 and len(current) > overlap:
                tail = current[-overlap:].strip()
                # couper au dernier espace pour éviter de tronquer un mot
                last_space = tail.rfind(" ")
                if last_space > 50:
                    tail = tail[last_space + 1:].strip()
                current = (tail + " " + para).strip() if tail else para
            else:
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


def main(args=None):
    if args is None:
        args = argparse.Namespace(md_only=False)
    DB_DIR.mkdir(exist_ok=True)

    _ocr_ok = _check_ocr()
    if not OCR_JOURNAL:
        print("  OCR des PDFs journal (L'ECHO) : desactive par defaut. INGEST_OCR_JOURNAL=1 pour activer.\n")

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
    try:
        import torch
        use_gpu = os.environ.get("USE_GPU") and torch.cuda.is_available()
        device = "cuda" if use_gpu else "cpu"
        if use_gpu:
            print(f"  GPU : {torch.cuda.get_device_name(0)}")
    except Exception:
        device = "cpu"
    model = SentenceTransformer(MODEL_NAME, device=device)

    all_docs, all_metadatas = [], []
    skipped = []

    # ── 1. Fichiers .md (sites web) en premier ───────────────────────────────────
    md_files = []
    if KNOWLEDGE_DIR.exists():
        md_files = sorted(KNOWLEDGE_DIR.glob("*.md"))
        if md_files:
            print(f"\n--- Fichiers .md / sites web ({len(md_files)} fichier(s)) ---\n")
        for md_path in md_files:
            try:
                raw = md_path.read_text(encoding="utf-8")
                source_url = ""
                for line in raw.split("\n")[:10]:
                    if line.strip().lower().startswith("source :"):
                        source_url = line.split(":", 1)[-1].strip()
                        break
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

    if md_files:
        print(f"\n  .md / sites web : {sum(m['year'] == 'web' for m in all_metadatas)} chunks.\n")

    # ── 2. PDFs (PV, L'ECHO) si demandé ─────────────────────────────────────────
    pdf_files = []
    if STATIC_DIR.exists():
        for p in sorted(STATIC_DIR.rglob("*.pdf")):
            if p.is_file():
                pdf_files.append(p)

    do_pdfs = not getattr(args, "md_only", False)
    if not do_pdfs:
        print("--- PDFs : non indexés (--md-only). ---\n")
    else:
        print(f"--- PDFs (static + journal) : {len(pdf_files)} fichier(s) ---\n")

    for pdf_path in pdf_files:
        if not do_pdfs:
            break
        date_iso, year = extract_date(pdf_path.name)
        if "journal" in str(pdf_path).replace("\\", "/"):
            rel_path = f"journal/{pdf_path.name}"
        else:
            rel_path = pdf_path.name
        print(f"  [{date_iso}] {pdf_path.name}", end=" ... ")

        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_text = []
                all_table_texts = []
                for p in pdf.pages:
                    page_content, table_texts = _extract_page_text_and_tables(p)
                    if page_content:
                        pages_text.append(page_content)
                    all_table_texts.extend(table_texts)

            is_journal = "journal" in str(pdf_path).replace("\\", "/")
            if not pages_text and _OCR_AVAILABLE:
                if is_journal and not OCR_JOURNAL:
                    print("ignore (OCR journaux desactive, INGEST_OCR_JOURNAL=1 pour activer)")
                    skipped.append(pdf_path.name)
                    continue
                try:
                    pages_text = extract_text_ocr(pdf_path)
                    if pages_text:
                        print("OCR", end=" ... ")
                except Exception as e:
                    print(f"OCR echoue ({e!r})", end=" ... ")
                    pages_text = []

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
            total_chunks = len(chunks) + len(all_table_texts)
            if all_table_texts:
                print(f"{len(chunks)} chunks + {len(all_table_texts)} tableau(x)", end=" ")
            else:
                print(f"{len(chunks)} chunks", end=" ")

            for i, chunk in enumerate(chunks):
                all_docs.append(chunk)
                all_metadatas.append({
                    "filename": pdf_path.name,
                    "rel_path": rel_path,
                    "date": date_iso,
                    "year": year,
                    "chunk": i,
                    "total_chunks": total_chunks,
                })
            # Chunks dédiés aux tableaux (barèmes, tarifs) pour améliorer la recherche sémantique
            for j, table_str in enumerate(all_table_texts):
                if len(table_str.strip()) < 20:
                    continue
                all_docs.append("[Tableau] " + table_str.strip())
                all_metadatas.append({
                    "filename": pdf_path.name,
                    "rel_path": rel_path,
                    "date": date_iso,
                    "year": year,
                    "chunk": len(chunks) + j,
                    "total_chunks": total_chunks,
                    "is_table": True,
                })
            print("")

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
    parser = argparse.ArgumentParser(description="Indexation .md (sites web) et PDFs pour Casimir.")
    parser.add_argument("--md-only", action="store_true", help="Indexer uniquement les .md (sites web), pas les PDFs")
    main(parser.parse_args())
