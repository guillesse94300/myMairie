"""
transform.py — Phase 2 : transformation source/ + static/ → input/

Lit tous les artefacts bruts de source/ et les PDFs de static/, les transforme
en fichiers .md propres dans input/ pour l'indexation par ingest.py.

Sources traitées (dans l'ordre) :
  source/images/{stem}/  → OCR → input/{stem}.md
  source/pdf/{stem}.pdf  → extraction texte (ou OCR) → input/{stem}.md
  static/*.pdf           → extraction texte (ou OCR) → input/{stem}.md
  source/md/{stem}.md    → validation/nettoyage → input/{stem}.md

Usage :
  python transform.py                # tout traiter (avec cache)
  python transform.py --force        # re-traiter même si input/{stem}.md existe
  python transform.py --no-static    # ignorer static/*.pdf
  python transform.py --stem xxx     # un seul stem spécifique
  python transform.py --only images  # seulement une catégorie (images|pdf|static|md)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Forcer UTF-8 sur la console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

_PROJECT   = Path(__file__).parent
SOURCE_DIR = _PROJECT / "source"
STATIC_DIR = _PROJECT / "static"
INPUT_DIR  = _PROJECT / "input"

_MIN_TEXT_CHARS = 150   # seuil minimum pour considérer le contenu valide


# ── Cache ────────────────────────────────────────────────────────────────────────

def _is_up_to_date(stem: str, source_mtime: float) -> bool:
    """True si input/{stem}.md existe et est plus récent que source_mtime."""
    dst = INPUT_DIR / f"{stem}.md"
    return dst.exists() and dst.stat().st_mtime >= source_mtime


# ── Écriture dans input/ ─────────────────────────────────────────────────────────

def _write_input(stem: str, title: str, source_ref: str, text: str) -> Path:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = INPUT_DIR / f"{stem}.md"
    content = (
        f"# {title}\n\n"
        f"Source : {source_ref}\n\n"
        f"---\n\n"
        f"{text.strip()}\n"
    )
    md_path.write_text(content, encoding="utf-8")
    return md_path


# ── PDF → texte ──────────────────────────────────────────────────────────────────

def _pdf_extract_text(pdf_path: Path) -> tuple[str, str]:
    """
    Extrait le texte d'un PDF.
    Essaie pdfplumber (texte natif) puis PyMuPDF+OCR en fallback.
    Retourne (texte, méthode_utilisée).
    """
    # — pdfplumber : extraction texte natif —
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t.strip())
        text = "\n\n".join(parts)
        if text and len(text) > _MIN_TEXT_CHARS:
            return text, "pdfplumber"
    except Exception as e:
        print(f"    pdfplumber : {e}")

    # — PyMuPDF + OCR : pour les PDFs image —
    try:
        import fitz
        from PIL import Image
        from fetcher.fetchers.calameo import _ocr_images

        doc = fitz.open(pdf_path)
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=200, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        doc.close()

        if images:
            text = _ocr_images(images)
            if text:
                return text, "ocr"
    except ImportError:
        pass
    except Exception as e:
        print(f"    ocr : {e}")

    return "", "none"


# ── Images → texte ───────────────────────────────────────────────────────────────

def _images_dir_to_text(img_dir: Path) -> str:
    """OCR sur toutes les images d'un répertoire (triées par nom)."""
    try:
        from PIL import Image
        from fetcher.fetchers.calameo import _ocr_images
    except ImportError:
        print("    Pillow ou fetcher.calameo non disponible")
        return ""

    files = sorted(
        p for p in img_dir.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg")
    )
    if not files:
        return ""

    images = [Image.open(p).convert("RGB") for p in files]
    return _ocr_images(images)


# ── Markdown → validation/nettoyage ─────────────────────────────────────────────

_BLOCK_MARKERS = [
    "paywall", "abonnez-vous", "access denied", "403 forbidden",
    "enable javascript", "anubis", "vous n'êtes pas un robot",
]


def _clean_md(content: str) -> tuple[str, list[str]]:
    """
    Nettoie un contenu markdown et retourne (contenu_nettoyé, avertissements).
    """
    warnings: list[str] = []

    # Caractères de remplacement UTF-8 (encodage cassé)
    if "\ufffd" in content:
        warnings.append("caractères mal encodés (U+FFFD) — vérifier la source")
        content = content.replace("\ufffd", "")

    # Supprimer les caractères de contrôle (sauf \t et \n)
    content = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", content)

    # Normaliser les fins de ligne et limiter les lignes vides consécutives
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    content = re.sub(r"\n{3,}", "\n\n", content)

    # Supprimer les lignes composées uniquement d'espaces
    lines = [ln if ln.strip() else "" for ln in content.splitlines()]
    content = "\n".join(lines)

    # Vérifier la longueur du contenu utile (hors en-tête)
    body = re.sub(r"#.*|Source.*|---", "", content).strip()
    if len(body) < _MIN_TEXT_CHARS:
        warnings.append(
            f"contenu très court ({len(body)} chars) — la source a peut-être bloqué l'accès"
        )

    # Détecter les signes de blocage/paywall
    content_lower = content.lower()
    for marker in _BLOCK_MARKERS:
        if marker in content_lower:
            warnings.append(f"possible blocage/paywall détecté : '{marker}'")
            break

    return content.strip(), warnings


# ── Traitements par type ─────────────────────────────────────────────────────────

def process_images(stem: str, force: bool = False) -> bool:
    img_dir = SOURCE_DIR / "images" / stem
    if not img_dir.exists():
        return False

    mtimes = [f.stat().st_mtime for f in img_dir.iterdir() if f.is_file()]
    src_mtime = max(mtimes) if mtimes else 0
    if not force and _is_up_to_date(stem, src_mtime):
        print(f"  [cache] {stem} (images)")
        return True

    print(f"  [images] {stem}/ — {len(list(img_dir.iterdir()))} fichier(s)... ", end="", flush=True)
    text = _images_dir_to_text(img_dir)
    if not text:
        print("aucun texte (OCR non disponible ?)")
        text = f"_Aucun texte OCR extrait depuis source/images/{stem}/._"
    else:
        print(f"{len(text)} chars")

    _write_input(stem, stem.replace("_", " "), f"source/images/{stem}/", text)
    return True


def process_pdf(pdf_path: Path, stem: str | None = None, force: bool = False) -> bool:
    stem = stem or pdf_path.stem
    if not force and _is_up_to_date(stem, pdf_path.stat().st_mtime):
        print(f"  [cache] {stem} (pdf)")
        return True

    print(f"  [pdf] {pdf_path.name}... ", end="", flush=True)
    text, method = _pdf_extract_text(pdf_path)

    if not text:
        print("aucun texte")
        text = f"_Aucun texte extrait depuis {pdf_path.name}._"
    else:
        print(f"{method}, {len(text)} chars")

    _write_input(stem, stem.replace("_", " "), pdf_path.name, text)
    return True


def process_md(md_path: Path, stem: str | None = None, force: bool = False) -> bool:
    stem = stem or md_path.stem
    if not force and _is_up_to_date(stem, md_path.stat().st_mtime):
        print(f"  [cache] {stem} (md)")
        return True

    content = md_path.read_text(encoding="utf-8")
    cleaned, warnings = _clean_md(content)

    for w in warnings:
        print(f"  [AVERT] {stem} : {w}")

    dst = INPUT_DIR / f"{stem}.md"
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    dst.write_text(cleaned + "\n", encoding="utf-8")

    status = f" [{len(warnings)} avert.]" if warnings else ""
    print(f"  [md] {stem} → {len(cleaned)} chars{status}")
    return True


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Phase 2 : transformation source/ + static/ → input/"
    )
    parser.add_argument("--no-static", action="store_true",
                        help="Ignorer static/*.pdf")
    parser.add_argument("--force", action="store_true",
                        help="Re-traiter même si input/{stem}.md est à jour")
    parser.add_argument("--stem", metavar="STEM",
                        help="Traiter un seul stem")
    parser.add_argument("--only", choices=["images", "pdf", "static", "md"],
                        help="Traiter uniquement une catégorie")
    args = parser.parse_args()

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = fail = 0

    def _run(fn, *a, **kw) -> bool:
        nonlocal ok, fail
        try:
            if fn(*a, **kw):
                ok += 1
                return True
        except Exception as e:
            print(f"  ERREUR : {e}")
            fail += 1
        return False

    # — Stem unique —
    if args.stem:
        s = args.stem
        if not _run(process_images, s, args.force):
            if not _run(process_pdf, SOURCE_DIR / "pdf" / f"{s}.pdf", s, args.force):
                if not _run(process_pdf, STATIC_DIR / f"{s}.pdf", s, args.force):
                    _run(process_md, SOURCE_DIR / "md" / f"{s}.md", s, args.force)
    else:
        do_all = args.only is None

        # — source/images/ —
        if do_all or args.only == "images":
            img_root = SOURCE_DIR / "images"
            if img_root.exists():
                stems = sorted(d.name for d in img_root.iterdir() if d.is_dir())
                if stems:
                    print(f"\n--- Images ({len(stems)}) ---")
                for stem in stems:
                    _run(process_images, stem, args.force)

        # — source/pdf/ —
        if do_all or args.only == "pdf":
            pdf_src = SOURCE_DIR / "pdf"
            if pdf_src.exists():
                pdfs = sorted(pdf_src.glob("*.pdf"))
                if pdfs:
                    print(f"\n--- PDFs source/ ({len(pdfs)}) ---")
                for pdf_path in pdfs:
                    _run(process_pdf, pdf_path, None, args.force)

        # — static/*.pdf —
        if (do_all or args.only == "static") and not args.no_static:
            if STATIC_DIR.exists():
                static_pdfs = sorted(p for p in STATIC_DIR.rglob("*.pdf") if p.is_file())
                if static_pdfs:
                    print(f"\n--- PDFs static/ ({len(static_pdfs)}) ---")
                for pdf_path in static_pdfs:
                    _run(process_pdf, pdf_path, pdf_path.stem, args.force)

        # — source/md/ —
        if do_all or args.only == "md":
            md_src = SOURCE_DIR / "md"
            if md_src.exists():
                mds = sorted(md_src.glob("*.md"))
                if mds:
                    print(f"\n--- Markdowns source/ ({len(mds)}) ---")
                for md_path in mds:
                    _run(process_md, md_path, None, args.force)

    print(f"\n{'=' * 50}")
    print(f"Résultat transform : {ok} traités, {fail} échec(s) → input/")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
