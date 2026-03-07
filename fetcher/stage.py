"""
fetcher/stage.py — Zone de staging pour les données brutes extraites.

Chaque URL extraite correspond à un répertoire fetcher_raw/{stem}/ contenant :
  manifest.json       — métadonnées et index des fichiers
  screenshot_001.png  — captures d'écran Playwright (Calameo, TripAdvisor...)
  page_001.jpg        — thumbnails CDN (Calameo CDN fallback)
  document.pdf        — PDF téléchargé directement
  raw_content.txt     — texte ou HTML brut (Wikipedia, sources textuelles)

Workflow :
  Phase 1  python -m fetcher extract <url>   → peuple le répertoire staging
  Phase 2  python -m fetcher interpret        → lit staging, produit .md + .pdf
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

# Répertoire de staging à la racine du projet (à côté de knowledge_sites/)
RAW_DIR = Path(__file__).parent.parent / "fetcher_raw"


@dataclass
class RawBundle:
    """
    Ensemble d'artefacts bruts extraits pour une URL donnée.
    Tous les chemins de fichiers sont relatifs à self.dir.
    """
    stem: str
    url: str
    source_type: str
    title: str = ""
    metadata: dict = field(default_factory=dict)

    # Fichiers présents dans le répertoire de staging
    screenshot_files: list[str] = field(default_factory=list)   # PNGs Playwright
    cdn_image_files: list[str] = field(default_factory=list)    # JPGs CDN
    pdf_file: str = ""          # PDF téléchargé directement
    raw_content_file: str = ""  # texte brut, HTML ou JSON API

    extracted_at: str = ""

    @property
    def dir(self) -> Path:
        """Répertoire de staging pour ce bundle."""
        return RAW_DIR / self.stem

    def screenshot_paths(self) -> list[Path]:
        return [self.dir / f for f in self.screenshot_files]

    def cdn_image_paths(self) -> list[Path]:
        return [self.dir / f for f in self.cdn_image_files]

    @property
    def pdf_path(self) -> Path | None:
        return (self.dir / self.pdf_file) if self.pdf_file else None

    @property
    def raw_content_path(self) -> Path | None:
        return (self.dir / self.raw_content_file) if self.raw_content_file else None


def init_bundle(url: str, stem: str, source_type: str) -> RawBundle:
    """Crée un RawBundle et initialise son répertoire de staging."""
    d = RAW_DIR / stem
    d.mkdir(parents=True, exist_ok=True)
    return RawBundle(
        stem=stem,
        url=url,
        source_type=source_type,
        extracted_at=datetime.now(timezone.utc).isoformat(),
    )


def save_bundle(bundle: RawBundle) -> Path:
    """Persiste le manifest.json du bundle dans son répertoire."""
    path = bundle.dir / "manifest.json"
    path.write_text(
        json.dumps(asdict(bundle), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_bundle(stem: str) -> RawBundle:
    """Charge un bundle depuis son répertoire de staging."""
    path = RAW_DIR / stem / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Bundle introuvable : {path}")
    return RawBundle(**json.loads(path.read_text(encoding="utf-8")))


def list_stems() -> list[str]:
    """Liste tous les stems disponibles dans le staging."""
    if not RAW_DIR.exists():
        return []
    return sorted(
        d.name for d in RAW_DIR.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    )
