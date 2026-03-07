"""
fetcher/output.py — Persistance des résultats.

- Texte → knowledge_sites/{safe_name}.md  (format identique à l'existant)
- PDF   → static/{safe_name}.pdf           (si FetchResult.pdf_bytes présent)
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .base import FetchResult

# Racine du projet (deux niveaux au-dessus de fetcher/)
_PROJECT_ROOT = Path(__file__).parent.parent
KNOWLEDGE_DIR = _PROJECT_ROOT / "knowledge_sites"
STATIC_DIR    = _PROJECT_ROOT / "static"


def _url_to_stem(url: str) -> str:
    """
    Génère un nom de fichier sûr (sans extension) depuis une URL.
    Ex : https://fr.wikipedia.org/wiki/Pierrefonds_(Oise)
         → fr_wikipedia_org_wiki_Pierrefonds__Oise_
    """
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "").replace(".", "_")
    path = parsed.path.strip("/").replace("/", "_")
    if not path:
        path = "index"
    stem = f"{domain}_{path}"[:80]
    return re.sub(r"[^\w\-]", "_", stem)


def _md_content(result: FetchResult) -> str:
    """Formate le résultat en markdown compatible knowledge_sites/."""
    lines = [
        f"# {result.title}",
        "",
        f"Source : {result.url}",
        "",
        "---",
        "",
        result.text.strip(),
    ]
    return "\n".join(lines) + "\n"


def save(result: FetchResult, dry_run: bool = False) -> dict[str, Path]:
    """
    Persiste le résultat sur disque.
    Retourne un dict {"md": Path, "pdf": Path|None}.
    En dry_run, affiche seulement ce qui serait écrit.
    """
    stem = _url_to_stem(result.url)
    paths: dict[str, Path | None] = {"md": None, "pdf": None}

    # — Markdown —
    md_path = KNOWLEDGE_DIR / f"{stem}.md"
    md_content = _md_content(result)
    if dry_run:
        print(f"[dry-run] Écrirait {md_path} ({len(md_content)} octets)")
        print(md_content[:500] + ("…" if len(md_content) > 500 else ""))
    else:
        KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")
        print(f"  .md → {md_path}")
    paths["md"] = md_path

    # — PDF (optionnel) —
    if result.pdf_bytes:
        pdf_path = STATIC_DIR / f"{stem}.pdf"
        if dry_run:
            print(f"[dry-run] Écrirait {pdf_path} ({len(result.pdf_bytes)} octets)")
        else:
            STATIC_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(result.pdf_bytes)
            print(f"  .pdf → {pdf_path}")
        paths["pdf"] = pdf_path

    return paths
