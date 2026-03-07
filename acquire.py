"""
acquire.py — Phase 1 : acquisition des documents depuis site_url.txt vers source/

Répertoires de sortie :
  source/images/{stem}/   ← captures d'écran PNG / thumbnails JPG (Calameo, JS-heavy)
  source/pdf/{stem}.pdf   ← PDFs téléchargés directement
  source/md/{stem}.md     ← texte extrait (Wikipedia, sites génériques, journaux)

Usage :
  python acquire.py                    # lit site_url.txt, saute les URLs déjà présentes
  python acquire.py --force            # re-télécharge tout
  python acquire.py --file urls.txt    # autre liste d'URLs
  python acquire.py --url https://...  # URL unique
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

# Forcer UTF-8 sur la console Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

_PROJECT  = Path(__file__).parent
SOURCE_DIR = _PROJECT / "source"
URL_FILE   = _PROJECT / "site_url.txt"


# ── Utilitaires ─────────────────────────────────────────────────────────────────

def _read_urls(path: Path) -> list[str]:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _already_acquired(stem: str) -> bool:
    """Vrai si ce stem est déjà présent dans au moins un sous-répertoire de source/."""
    return (
        (SOURCE_DIR / "images" / stem).exists()
        or (SOURCE_DIR / "pdf" / f"{stem}.pdf").exists()
        or (SOURCE_DIR / "md" / f"{stem}.md").exists()
    )


def _deposit(bundle) -> dict:
    """
    Copie les artefacts du staging fetcher_raw/{stem}/ vers les sous-répertoires source/.
    Retourne un dict résumant ce qui a été déposé.
    """
    result = {"stem": bundle.stem, "url": bundle.url, "deposited": []}

    # — Images (screenshots Playwright + thumbnails CDN) —
    img_files = bundle.screenshot_files + bundle.cdn_image_files
    if img_files:
        img_dir = SOURCE_DIR / "images" / bundle.stem
        img_dir.mkdir(parents=True, exist_ok=True)
        for fname in img_files:
            src = bundle.dir / fname
            if src.exists():
                shutil.copy2(src, img_dir / fname)
        result["deposited"].append(f"images/{bundle.stem}/ ({len(img_files)} fichier(s))")

    # — PDF direct —
    if bundle.pdf_file and bundle.pdf_path and bundle.pdf_path.exists():
        pdf_dst = SOURCE_DIR / "pdf" / f"{bundle.stem}.pdf"
        pdf_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundle.pdf_path, pdf_dst)
        result["deposited"].append(f"pdf/{bundle.stem}.pdf")

    # — Texte brut → .md formaté pour knowledge_sites —
    if bundle.raw_content_file and bundle.raw_content_path and bundle.raw_content_path.exists():
        content = bundle.raw_content_path.read_text(encoding="utf-8")
        md_dst = SOURCE_DIR / "md" / f"{bundle.stem}.md"
        md_dst.parent.mkdir(parents=True, exist_ok=True)
        md_content = (
            f"# {bundle.title or bundle.stem}\n\n"
            f"Source : {bundle.url}\n\n"
            f"---\n\n"
            f"{content.strip()}\n"
        )
        md_dst.write_text(md_content, encoding="utf-8")
        result["deposited"].append(f"md/{bundle.stem}.md")

    return result


# ── Acquisition d'une URL ────────────────────────────────────────────────────────

def acquire_url(url: str, force: bool = False) -> dict:
    """
    Acquiert une URL, dépose les artefacts dans source/ et nettoie le staging.
    Si l'URL est déjà présente et force=False, retourne immédiatement (cache).
    """
    from fetcher import extract_raw
    from fetcher.output import _url_to_stem

    stem = _url_to_stem(url)

    if not force and _already_acquired(stem):
        return {"stem": stem, "url": url, "deposited": [], "cached": True}

    bundle = extract_raw(url)
    result = _deposit(bundle)

    # Nettoyage du staging temporaire (fetcher_raw/{stem}/)
    try:
        shutil.rmtree(bundle.dir)
    except Exception:
        pass

    return result


# ── Point d'entrée ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Phase 1 : acquisition depuis site_url.txt vers source/"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--url", metavar="URL", help="URL unique à acquérir")
    group.add_argument("--file", "-f", metavar="FICHIER", default=str(URL_FILE),
                       help=f"Fichier d'URLs (défaut : {URL_FILE.name})")
    parser.add_argument("--force", action="store_true",
                        help="Re-télécharger même si déjà présent dans source/")
    parser.add_argument("--delay", type=float, default=1.5, metavar="SEC",
                        help="Délai entre requêtes (défaut : 1.5s)")
    args = parser.parse_args()

    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    if args.url:
        urls = [args.url]
    else:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"Fichier introuvable : {file_path}", file=sys.stderr)
            sys.exit(1)
        urls = _read_urls(file_path)

    print(f"Acquisition de {len(urls)} URL(s) → source/")
    print(f"  images → source/images/")
    print(f"  pdf    → source/pdf/")
    print(f"  md     → source/md/\n")

    ok = fail = cached = 0
    for i, url in enumerate(urls):
        print(f"[{i + 1}/{len(urls)}] {url}")
        try:
            result = acquire_url(url, force=args.force)
            if result.get("cached"):
                print(f"  [cache] {result['stem']}")
                cached += 1
            else:
                for item in result["deposited"]:
                    print(f"  → source/{item}")
                if not result["deposited"]:
                    print("  (rien déposé)")
                ok += 1
        except Exception as e:
            print(f"  ERREUR : {type(e).__name__}: {e}")
            fail += 1

        if i < len(urls) - 1:
            time.sleep(args.delay)

    print(f"\n{'=' * 50}")
    print(f"Résultat acquire : {ok} acquis, {cached} en cache, {fail} échec(s)")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
