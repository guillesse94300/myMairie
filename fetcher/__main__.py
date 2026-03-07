"""
fetcher/__main__.py — Interface en ligne de commande.

Commandes disponibles :

  Comportement historique (extraction + interprétation en une passe) :
    python -m fetcher <url>
    python -m fetcher <url> --dry-run
    python -m fetcher --file site_url.txt
    python -m fetcher --detect <url>

  Nouvelle commande — Phase 1, extraction brute → fetcher_raw/ :
    python -m fetcher extract <url>
    python -m fetcher extract --file site_url.txt

  Nouvelle commande — Phase 2, interprétation depuis le staging :
    python -m fetcher interpret               # tous les bundles en staging
    python -m fetcher interpret <stem>        # un seul stem
    python -m fetcher interpret --dry-run

  Liste des bundles en staging :
    python -m fetcher list
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Forcer UTF-8 sur la console Windows pour éviter les UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from .base import FetchError
from .dispatcher import detect_type, get_fetcher
from . import fetch_and_save


# ── Commande historique : run (extract + interpret) ────────────────────────────

def _read_urls(file_path: Path) -> list[str]:
    """Lit une liste d'URLs depuis un fichier (ignore commentaires et lignes vides)."""
    urls = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def _run_url(url: str, dry_run: bool) -> bool:
    """Exécute extraction + interprétation pour une URL. Retourne True si succès."""
    detected = detect_type(url)
    print(f"\n[{detected.upper()}] {url}")
    try:
        out = fetch_and_save(url, dry_run=dry_run)
        result = out["result"]
        paths = out["paths"]
        print(f"  Titre   : {result.title}")
        print(f"  Texte   : {len(result.text)} caractères")
        if result.pdf_bytes:
            print(f"  PDF     : {len(result.pdf_bytes)} octets")
        if not dry_run:
            print(f"  Sauvé   : {paths['md']}")
            if paths.get("pdf"):
                print(f"  PDF     : {paths['pdf']}")
        return True
    except FetchError as e:
        print(f"  ECHEC   : {e}")
        return False
    except Exception as e:
        print(f"  ERREUR  : {type(e).__name__}: {e}")
        return False


def _cmd_run(args) -> None:
    """Comportement historique : extraction + interprétation en une passe."""
    if args.url:
        ok = _run_url(args.url, args.dry_run)
        sys.exit(0 if ok else 1)

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Fichier introuvable : {file_path}", file=sys.stderr)
        sys.exit(1)

    urls = _read_urls(file_path)
    print(f"{len(urls)} URL(s) à traiter depuis {file_path}")
    if args.dry_run:
        print("[dry-run activé — aucun fichier ne sera écrit]")

    ok_count = fail_count = 0
    for i, url in enumerate(urls):
        if _run_url(url, args.dry_run):
            ok_count += 1
        else:
            fail_count += 1
        if i < len(urls) - 1:
            time.sleep(args.delay)

    print(f"\n{'=' * 50}")
    print(f"Résultat : {ok_count} succès, {fail_count} échec(s) sur {len(urls)} URL(s)")
    sys.exit(0 if fail_count == 0 else 1)


# ── Commande extract (Phase 1) ─────────────────────────────────────────────────

def _extract_url(url: str) -> bool:
    """Extrait les artefacts bruts d'une URL dans le staging. Retourne True si succès."""
    detected = detect_type(url)
    print(f"\n[{detected.upper()}] {url}")
    try:
        fetcher = get_fetcher(url)
        bundle = fetcher.extract_raw(url)
        print(f"  Titre   : {bundle.title}")
        print(f"  Screenshots : {len(bundle.screenshot_files)}")
        print(f"  CDN images  : {len(bundle.cdn_image_files)}")
        print(f"  PDF direct  : {'oui' if bundle.pdf_file else 'non'}")
        print(f"  Stem        : {bundle.stem}")
        return True
    except FetchError as e:
        print(f"  ECHEC   : {e}")
        return False
    except Exception as e:
        print(f"  ERREUR  : {type(e).__name__}: {e}")
        return False


def _cmd_extract(args) -> None:
    """Phase 1 : extraction brute → fetcher_raw/."""
    if args.url:
        ok = _extract_url(args.url)
        sys.exit(0 if ok else 1)

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Fichier introuvable : {file_path}", file=sys.stderr)
        sys.exit(1)

    urls = _read_urls(file_path)
    print(f"{len(urls)} URL(s) à extraire depuis {file_path}")

    ok_count = fail_count = 0
    for i, url in enumerate(urls):
        if _extract_url(url):
            ok_count += 1
        else:
            fail_count += 1
        if i < len(urls) - 1:
            time.sleep(args.delay)

    print(f"\n{'=' * 50}")
    print(f"Résultat extract : {ok_count} succès, {fail_count} échec(s) sur {len(urls)}")
    sys.exit(0 if fail_count == 0 else 1)


# ── Commande interpret (Phase 2) ───────────────────────────────────────────────

def _interpret_stem(stem: str, dry_run: bool) -> bool:
    """Interprète un bundle depuis le staging et produit .md + .pdf. Retourne True si succès."""
    from .stage import load_bundle
    from .dispatcher import get_fetcher_for_type
    from .output import save

    try:
        bundle = load_bundle(stem)
        print(f"\n[{bundle.source_type.upper()}] {bundle.url}")

        fetcher = get_fetcher_for_type(bundle.source_type)
        result = fetcher.interpret(bundle)

        print(f"  Titre   : {result.title}")
        print(f"  Texte   : {len(result.text)} caractères")
        if result.pdf_bytes:
            print(f"  PDF     : {len(result.pdf_bytes)} octets")

        if not dry_run:
            paths = save(result)
            print(f"  .md → {paths['md']}")
            if paths.get("pdf"):
                print(f"  .pdf → {paths['pdf']}")
        else:
            print(f"  [dry-run] {stem}")
        return True
    except FileNotFoundError as e:
        print(f"  ECHEC : {e}")
        return False
    except Exception as e:
        print(f"  ERREUR  : {type(e).__name__}: {e}")
        return False


def _cmd_interpret(args) -> None:
    """Phase 2 : interprétation depuis fetcher_raw/ → knowledge_sites/ + static/."""
    from .stage import list_stems

    stems = [args.stem] if args.stem else list_stems()

    if not stems:
        print("Aucun bundle en staging. Lancez d'abord : python -m fetcher extract <url>")
        sys.exit(0)

    print(f"{len(stems)} bundle(s) à interpréter")
    if args.dry_run:
        print("[dry-run activé — aucun fichier ne sera écrit]")

    ok_count = fail_count = 0
    for stem in stems:
        if _interpret_stem(stem, args.dry_run):
            ok_count += 1
        else:
            fail_count += 1

    print(f"\n{'=' * 50}")
    print(f"Résultat interpret : {ok_count} succès, {fail_count} échec(s) sur {len(stems)}")
    sys.exit(0 if fail_count == 0 else 1)


# ── Commande list ──────────────────────────────────────────────────────────────

def _cmd_list() -> None:
    """Liste les bundles disponibles dans le staging."""
    from .stage import list_stems, load_bundle, RAW_DIR

    stems = list_stems()
    if not stems:
        print(f"Aucun bundle dans {RAW_DIR}")
        return

    print(f"{len(stems)} bundle(s) dans {RAW_DIR} :\n")
    for stem in stems:
        try:
            b = load_bundle(stem)
            nb_img = len(b.screenshot_files) + len(b.cdn_image_files)
            flags = []
            if b.screenshot_files:
                flags.append(f"{len(b.screenshot_files)} screenshots")
            if b.cdn_image_files:
                flags.append(f"{len(b.cdn_image_files)} CDN imgs")
            if b.pdf_file:
                flags.append("PDF direct")
            detail = ", ".join(flags) if flags else "texte brut"
            print(f"  {stem}")
            print(f"    url     : {b.url}")
            print(f"    titre   : {b.title or '(sans titre)'}")
            print(f"    contenu : {detail}")
            print(f"    extrait : {b.extracted_at[:10]}")
        except Exception as e:
            print(f"  {stem}  [erreur : {e}]")


# ── Point d'entrée principal ───────────────────────────────────────────────────

def main():
    # Dispatch par premier argument non-flag
    first = next((a for a in sys.argv[1:] if not a.startswith("-")), "")

    if first == "extract":
        parser = argparse.ArgumentParser(prog="python -m fetcher extract",
                                         description="Phase 1 : extraction brute → fetcher_raw/")
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("url", nargs="?", help="URL à extraire")
        group.add_argument("--file", "-f", metavar="FICHIER",
                           help="Fichier d'URLs (une par ligne, # ignoré)")
        parser.add_argument("--delay", type=float, default=1.5, metavar="SEC")
        # Retirer "extract" de argv avant parsing
        args = parser.parse_args(sys.argv[2:])
        _cmd_extract(args)

    elif first == "interpret":
        parser = argparse.ArgumentParser(prog="python -m fetcher interpret",
                                         description="Phase 2 : interprétation depuis fetcher_raw/")
        parser.add_argument("stem", nargs="?", help="Stem spécifique (défaut : tous)")
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(sys.argv[2:])
        _cmd_interpret(args)

    elif first == "list":
        _cmd_list()

    else:
        # Comportement historique
        parser = argparse.ArgumentParser(
            prog="python -m fetcher",
            description="Acquisition de documents pour la base de connaissance Casimir.",
            epilog="Sous-commandes : extract | interpret | list",
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("url", nargs="?", help="URL à récupérer")
        group.add_argument("--file", "-f", metavar="FICHIER")
        group.add_argument("--detect", metavar="URL",
                           help="Affiche le type de handler détecté (sans fetch)")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--delay", type=float, default=1.5, metavar="SEC")

        args = parser.parse_args()

        if args.detect:
            t = detect_type(args.detect)
            print(f"Type détecté : {t}")
            return

        _cmd_run(args)


if __name__ == "__main__":
    main()
