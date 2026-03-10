"""
transform.py -- Phase 2 : transformation source/ + static/ -> input/

Sources traitees :
  source/images/{stem}/  -> OCR -> input/{stem}.md    (repertoires d'images)
  source/images/*.jpg    -> OCR -> input/{stem}.md    (images isolees)
  source/pdf/*.pdf       -> extraction texte/OCR -> input/{stem}.md
  static/**/*.pdf        -> extraction texte/OCR -> input/{stem}.md
  source/md/*.md         -> nettoyage agressif (nav/boilerplate) -> input/{stem}.md
  static/*.md            -> nettoyage leger -> input/{stem}.md

Usage :
  python transform.py                 # tout traiter (avec cache)
  python transform.py --force         # re-traiter meme si input/*.md existe
  python transform.py --only images   # une seule categorie : images | pdf | md
  python transform.py --stem xxx      # un seul stem specifique
  python transform.py --log logs/run.log
  python transform.py --no-static     # ignorer static/
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

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

_MIN_TEXT_CHARS = 150

# ==========================================================================
# Logging
# ==========================================================================

_log_file = None


def _log(msg: str = "") -> None:
    """Affiche avec timestamp; ecrit aussi dans le fichier de log si ouvert."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def _log_raw(msg: str = "") -> None:
    """Affiche sans timestamp (separateurs, lignes vides)."""
    print(msg)
    if _log_file:
        _log_file.write(msg + "\n")
        _log_file.flush()


def _banner(title: str) -> None:
    sep = "-" * 60
    _log_raw(f"\n{sep}")
    _log_raw(f"  {title}")
    _log_raw(sep)


# ==========================================================================
# Cache
# ==========================================================================

def _is_up_to_date(stem: str, source_mtime: float) -> bool:
    """True si input/{stem}.md existe et est plus recent que source_mtime."""
    dst = INPUT_DIR / f"{stem}.md"
    return dst.exists() and dst.stat().st_mtime >= source_mtime


# ==========================================================================
# Ecriture dans input/
# ==========================================================================

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


# ==========================================================================
# Nettoyage Markdown
# ==========================================================================

# Lignes boilerplate a supprimer (correspondance exacte, apres normalisation)
_NAV_EXACT = frozenset({
    # Interface web generique
    "accueil", "menu", "fermer", "rechercher", "connexion", "se connecter",
    "s inscrire", "inscription", "abonnez-vous", "mon compte", "panier",
    "lire plus", "en savoir plus", "voir plus", "afficher plus",
    # Navigation OpenEdition
    "table des matieres", "citer", "partager", "formats de lecture",
    "naviguer dans le livre", "informations sur la couverture",
    "plan detaille", "texte integral", "dans la meme collection",
    "voir plus de livres", "voir tous les livres", "tous droits reserves",
    # Tourisme / evenements
    "voir tous les horaires", "reserver votre billet", "reserver",
    "voir tous les evenements", "voir toutes les dates disponibles",
    "voir toutes les dates", "voir l agenda", "incontournable",
    # Formats numeriques
    "pdf", "epub", "html", "mobi",
    # Reseaux sociaux
    "like", "tweet", "commenter", "commentaires",
    # Divers
    "chargement", "loading", "veuillez patienter", "enable javascript",
})

# Prefixes de lignes de navigation (apres normalisation)
_NAV_PREFIXES = (
    "naviguer dans ",
    "voir plus de ",
    "voir tous les ",
    "voir toutes les ",
    "ce livre est recense",
    "le texte seul est utilisable",
    "licence openedition",
    "dans la meme collection",
    "lire l histoire",
    "reserver votre",
    "articles lies",
    "en savoir plus sur",
    "retour a ",
    "aller a ",
    "partager sur ",
    "newsletter",
)

# Marqueurs de blocage/paywall
_BLOCK_MARKERS = [
    "paywall", "abonnez-vous", "access denied", "403 forbidden",
    "enable javascript", "anubis",
]

# Table de translitteration des accents courants
_ACCENT_MAP = str.maketrans(
    "\xe9\xe8\xea\xeb\xe0\xe2\xf4\xf9\xfb\xee\xef\xe7\u2019\u2018\u201c\u201d",
    "eeeeaaouuiic" + "'" + "'" + '"' + '"',
)


def _normalize(s: str) -> str:
    """Minuscule + translitteration des accents pour comparaison."""
    return s.lower().translate(_ACCENT_MAP)


def _parse_md_header(content: str) -> tuple[str, str, str]:
    """
    Extrait le header standard :
        # Titre
        Source : ref
        ---
        <corps>
    Retourne (titre, source_ref, corps).
    Si le format n'est pas reconnu, corps = tout le contenu.
    """
    lines = content.split("\n")
    title = source_ref = ""
    body_start = 0
    found_sep = False
    for i, line in enumerate(lines):
        s = line.strip()
        if not title and s.startswith("# "):
            title = s[2:].strip()
        elif not source_ref and re.match(r"^[Ss]ource\s*:", s):
            source_ref = re.split(r":\s*", s, maxsplit=1)[-1].strip()
        elif s == "---":
            body_start = i + 1
            found_sep = True
            break
    body = "\n".join(lines[body_start:]) if found_sep else content
    return title, source_ref, body


def _strip_nav_boilerplate(text: str) -> str:
    """
    Supprime les lignes de navigation et boilerplate d'un texte web scrappe.
    Conserve les vrais paragraphes (texte continu, listes de contenu).
    """
    cleaned: list[str] = []
    prev_blank = False
    for line in text.split("\n"):
        stripped = line.strip()

        # Lignes vides : conserver max 1 consecutive
        if not stripped:
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
            continue
        prev_blank = False

        norm = _normalize(stripped)

        # Correspondance exacte avec les patterns nav
        if norm in _NAV_EXACT:
            continue

        # Prefixes nav
        if any(norm.startswith(p) for p in _NAV_PREFIXES):
            continue

        # Numeros de page isoles : "p. 12", "p. 09-10", "- 12 -"
        if re.match(r"^[p.\-\s]*\d{1,4}(\s*[\-]\s*\d{1,4})?[p.\-\s]*$", stripped):
            continue

        # Ligne tres courte (<=3 mots) sans ponctuation significative -> probable nav
        words = stripped.split()
        has_punct = bool(re.search(r"[.,:;!?()\[\]0-9]", stripped))
        if len(words) <= 3 and not has_punct:
            if not re.match(r"^\d", stripped) and not stripped.startswith(("-", "*")):
                continue

        cleaned.append(line)

    result = "\n".join(cleaned).strip()
    return re.sub(r"\n{3,}", "\n\n", result)


def _clean_text(text: str) -> tuple[str, list[str]]:
    """Nettoyage de base (encodage, ctrl, espaces). Retourne (texte, avertissements)."""
    warns: list[str] = []
    if "\ufffd" in text:
        warns.append("caracteres mal encodes (U+FFFD)")
        text = text.replace("\ufffd", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln if ln.strip() else "" for ln in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), warns


def _check_quality(body: str) -> list[str]:
    """Retourne liste d'avertissements qualite."""
    warns: list[str] = []
    if len(body) < _MIN_TEXT_CHARS:
        warns.append(f"contenu tres court ({len(body)} chars) -- acces bloque ?")
    body_lower = body.lower()
    for marker in _BLOCK_MARKERS:
        if marker in body_lower:
            warns.append(f"possible blocage/paywall : {marker!r}")
            break
    return warns


# ==========================================================================
# PDF -> texte
# ==========================================================================

def _pdf_extract_text(pdf_path: Path) -> tuple[str, str]:
    """
    Extrait le texte d'un PDF.
    1. pdfplumber (texte natif)
    2. PyMuPDF + OCR Tesseract (fallback PDF image)
    Retourne (texte, methode).
    """
    # -- pdfplumber : extraction texte natif --
    try:
        import pdfplumber
        parts: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(t.strip())
        text = "\n\n".join(parts)
        if text and len(text) > _MIN_TEXT_CHARS:
            return text, "pdfplumber"
    except Exception as e:
        _log(f"    pdfplumber : {e}")

    # -- PyMuPDF + OCR : pour les PDFs image --
    try:
        import fitz
        from PIL import Image
        from fetcher.fetchers.calameo import _ocr_images
        doc = fitz.open(pdf_path)
        images: list[Image.Image] = []
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
        _log(f"    ocr : {e}")

    return "", "none"


# ==========================================================================
# Images -> texte (OCR)
# ==========================================================================

def _ocr_image_list(image_paths: list[Path]) -> str:
    """OCR sur une liste de fichiers image."""
    try:
        from PIL import Image
        from fetcher.fetchers.calameo import _ocr_images
    except ImportError:
        _log("  Pillow ou fetcher.calameo non disponible pour l'OCR")
        return ""
    images = [Image.open(p).convert("RGB") for p in image_paths]
    return _ocr_images(images)


# ==========================================================================
# Traitements par type
# ==========================================================================

def process_images_dir(stem: str, force: bool = False) -> bool:
    """OCR sur un repertoire source/images/{stem}/."""
    img_dir = SOURCE_DIR / "images" / stem
    if not img_dir.exists():
        return False
    image_files = sorted(
        p for p in img_dir.iterdir()
        if p.suffix.lower() in (".png", ".jpg", ".jpeg") and p.is_file()
    )
    if not image_files:
        _log(f"  [SKIP] {stem}/ -- aucun fichier image")
        return False
    src_mtime = max(f.stat().st_mtime for f in image_files)
    if not force and _is_up_to_date(stem, src_mtime):
        _log(f"  [cache] {stem}/")
        return True
    t0 = time.time()
    _log(f"  [image-dir] {stem}/ ({len(image_files)} image(s))...")
    text = _ocr_image_list(image_files)
    if not text:
        _log("    -> aucun texte extrait (OCR non disponible ?)")
        text = f"_Aucun texte OCR extrait depuis source/images/{stem}/._"
    else:
        _log(f"    -> OCR : {len(text):,} chars en {time.time()-t0:.1f}s")
    _write_input(stem, stem.replace("_", " "), f"source/images/{stem}/", text)
    return True


def process_image_file(img_path: Path, force: bool = False) -> bool:
    """OCR sur un fichier image isole dans source/images/."""
    stem = img_path.stem
    if not force and _is_up_to_date(stem, img_path.stat().st_mtime):
        _log(f"  [cache] {img_path.name}")
        return True
    t0 = time.time()
    _log(f"  [image] {img_path.name}...")
    text = _ocr_image_list([img_path])
    if not text:
        _log("    -> aucun texte extrait")
        text = f"_Aucun texte OCR extrait depuis {img_path.name}._"
    else:
        _log(f"    -> OCR : {len(text):,} chars en {time.time()-t0:.1f}s")
    _write_input(stem, stem.replace("_", " "), img_path.name, text)
    return True


def process_pdf(pdf_path: Path, stem: str | None = None, force: bool = False) -> bool:
    """Extrait le texte d'un PDF (natif ou OCR) -> input/{stem}.md."""
    stem = stem or pdf_path.stem
    if not force and _is_up_to_date(stem, pdf_path.stat().st_mtime):
        _log(f"  [cache] {pdf_path.name}")
        return True
    t0 = time.time()
    _log(f"  [pdf] {pdf_path.name}...")
    text, method = _pdf_extract_text(pdf_path)
    if not text:
        _log("    -> aucun texte extrait")
        text = f"_Aucun texte extrait depuis {pdf_path.name}._"
    else:
        _log(f"    -> {method} : {len(text):,} chars en {time.time()-t0:.1f}s")
    title = stem.replace("-", " ").replace("_", " ")
    _write_input(stem, title, pdf_path.name, text)
    return True


def process_source_md(md_path: Path, stem: str | None = None, force: bool = False) -> bool:
    """
    Traitement source/md/ (page web scrappee) :
    - Parse l'en-tete (# Titre / Source / ---)
    - Nettoyage agressif du corps (nav, boilerplate)
    - Ecrit dans input/ au format standard
    """
    stem = stem or md_path.stem
    if not force and _is_up_to_date(stem, md_path.stat().st_mtime):
        _log(f"  [cache] {md_path.name}")
        return True
    t0 = time.time()
    content = md_path.read_text(encoding="utf-8")
    content, enc_warns = _clean_text(content)
    title, source_ref, body = _parse_md_header(content)
    body_before = len(body)
    body = _strip_nav_boilerplate(body)
    body, _ = _clean_text(body)
    removed = body_before - len(body)
    qual_warns = _check_quality(body)
    all_warns = enc_warns + qual_warns
    for w in all_warns:
        _log(f"    [AVERT] {w}")
    status = f" [{len(all_warns)} avert.]" if all_warns else ""
    _log(
        f"  [md-web] {md_path.name} -> "
        f"{len(body):,} chars (-{removed:,} nav) en {time.time()-t0:.1f}s{status}"
    )
    if not title:
        title = stem.replace("_", " ")
    if not source_ref:
        source_ref = md_path.name
    _write_input(stem, title, source_ref, body)
    return True


def process_static_md(md_path: Path, stem: str | None = None, force: bool = False) -> bool:
    """
    Traitement static/*.md (deja converti depuis PDF) :
    nettoyage leger uniquement (encodage, espaces).
    """
    stem = stem or md_path.stem
    if not force and _is_up_to_date(stem, md_path.stat().st_mtime):
        _log(f"  [cache] {md_path.name}")
        return True
    t0 = time.time()
    content = md_path.read_text(encoding="utf-8")
    content, enc_warns = _clean_text(content)
    qual_warns = _check_quality(content)
    all_warns = enc_warns + qual_warns
    for w in all_warns:
        _log(f"    [AVERT] {w}")
    status = f" [{len(all_warns)} avert.]" if all_warns else ""
    _log(
        f"  [md-stat] {md_path.name} -> "
        f"{len(content):,} chars en {time.time()-t0:.1f}s{status}"
    )
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    (INPUT_DIR / f"{stem}.md").write_text(content + "\n", encoding="utf-8")
    return True


# ==========================================================================
# Compteurs et helpers globaux
# ==========================================================================

_total_ok = _total_fail = _total_skip = 0


def _run(fn, *a, **kw) -> str:
    """Lance fn, comptabilise, retourne 'ok'/'skip'/'fail'."""
    global _total_ok, _total_fail, _total_skip
    try:
        result = fn(*a, **kw)
        if result:
            _total_ok += 1
            return "ok"
        else:
            _total_skip += 1
            return "skip"
    except Exception as e:
        _log(f"    ERREUR : {e}")
        _total_fail += 1
        return "fail"


def _print_summary(t0: float) -> None:
    elapsed = time.time() - t0
    _log_raw("\n" + "=" * 60)
    _log(
        f"Resultat : {_total_ok} traites  |  {_total_skip} ignores  "
        f"|  {_total_fail} echec(s)  |  {elapsed:.1f}s"
    )
    _log(f"Destination : {INPUT_DIR}")
    if _total_fail:
        _log("ATTENTION : des erreurs se sont produites -- verifiez les logs.")
    _log_raw("=" * 60)


def _close_log() -> None:
    global _log_file
    if _log_file:
        _log_file.close()
        _log_file = None


# ==========================================================================
# Main
# ==========================================================================

def main() -> None:
    global _log_file

    parser = argparse.ArgumentParser(
        description="Phase 2 : transformation source/ + static/ -> input/"
    )
    parser.add_argument(
        "--only", choices=["images", "pdf", "md"],
        help="Traiter uniquement une categorie (images | pdf | md)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-traiter meme si input/{stem}.md est a jour",
    )
    parser.add_argument(
        "--stem", metavar="STEM",
        help="Traiter un seul stem specifique",
    )
    parser.add_argument(
        "--log", metavar="FICHIER",
        help="Ecrire les logs dans ce fichier en plus de stdout",
    )
    parser.add_argument(
        "--no-static", action="store_true",
        help="Ignorer les fichiers de static/",
    )
    args = parser.parse_args()

    # Ouvrir le fichier de log si demande
    if args.log:
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_file = log_path.open("w", encoding="utf-8")

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    t_global = time.time()

    _log_raw("\n" + "=" * 60)
    _log("TRANSFORM -- source/ + static/ -> input/")
    mode_str = "--force (tout retraiter)" if args.force else "cache actif"
    _log(f"Mode : {mode_str}")
    if args.log:
        _log(f"Log  : {args.log}")
    _log_raw("=" * 60)

    # -- Stem unique ---------------------------------------------------------
    if args.stem:
        s = args.stem
        _banner(f"Stem unique : {s}")
        img_dir  = SOURCE_DIR / "images" / s
        pdf_src  = SOURCE_DIR / "pdf" / f"{s}.pdf"
        pdf_stat = STATIC_DIR / f"{s}.pdf"
        md_src   = SOURCE_DIR / "md" / f"{s}.md"
        md_stat  = STATIC_DIR / f"{s}.md"
        if img_dir.is_dir():
            _run(process_images_dir, s, args.force)
        elif pdf_src.exists():
            _run(process_pdf, pdf_src, s, args.force)
        elif pdf_stat.exists():
            _run(process_pdf, pdf_stat, s, args.force)
        elif md_src.exists():
            _run(process_source_md, md_src, s, args.force)
        elif md_stat.exists():
            _run(process_static_md, md_stat, s, args.force)
        else:
            _log(f"  Aucune source trouvee pour le stem {s!r}")
        _print_summary(t_global)
        _close_log()
        sys.exit(0 if _total_fail == 0 else 1)

    do_all = args.only is None

    # -- IMAGES --------------------------------------------------------------
    if do_all or args.only == "images":
        img_root = SOURCE_DIR / "images"
        if img_root.exists():
            subdirs = sorted(d for d in img_root.iterdir() if d.is_dir())
            loose   = sorted(
                p for p in img_root.iterdir()
                if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
            )
            if subdirs or loose:
                _banner(f"Images ({len(subdirs)} repertoires + {len(loose)} isolees)")
                for d in subdirs:
                    _run(process_images_dir, d.name, args.force)
                for f in loose:
                    _run(process_image_file, f, args.force)
            else:
                _log("  Aucun fichier image trouve dans source/images/")
        else:
            _log("  source/images/ introuvable -- categorie ignoree")

    # -- PDFs : source/pdf/ + static/**/*.pdf --------------------------------
    if do_all or args.only == "pdf":
        pdf_src_dir = SOURCE_DIR / "pdf"
        src_pdfs = sorted(pdf_src_dir.glob("*.pdf")) if pdf_src_dir.exists() else []
        stat_pdfs: list[Path] = []
        if not args.no_static and STATIC_DIR.exists():
            stat_pdfs = sorted(p for p in STATIC_DIR.rglob("*.pdf") if p.is_file())
        total_pdfs = len(src_pdfs) + len(stat_pdfs)
        if total_pdfs:
            _banner(
                f"PDFs ({len(src_pdfs)} source/pdf + {len(stat_pdfs)} static = {total_pdfs})"
            )
            for p in src_pdfs:
                _run(process_pdf, p, None, args.force)
            for p in stat_pdfs:
                _run(process_pdf, p, p.stem, args.force)
        else:
            _log("  Aucun PDF trouve")

    # -- MARKDOWN : source/md/ + static/*.md ---------------------------------
    if do_all or args.only == "md":
        md_src_dir = SOURCE_DIR / "md"
        src_mds = sorted(md_src_dir.glob("*.md")) if md_src_dir.exists() else []
        stat_mds: list[Path] = []
        if not args.no_static and STATIC_DIR.exists():
            stat_mds = sorted(p for p in STATIC_DIR.glob("*.md") if p.is_file())
        total_mds = len(src_mds) + len(stat_mds)
        if total_mds:
            _banner(
                f"Markdown ({len(src_mds)} source/md + {len(stat_mds)} static = {total_mds})"
            )
            for p in src_mds:
                _run(process_source_md, p, None, args.force)
            for p in stat_mds:
                _run(process_static_md, p, None, args.force)
        else:
            _log("  Aucun fichier Markdown trouve")

    _print_summary(t_global)
    _close_log()
    sys.exit(0 if _total_fail == 0 else 1)


if __name__ == "__main__":
    main()
