"""
fetcher/base.py — Types de base pour le service d'acquisition de documents.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FetchResult:
    """Résultat d'une récupération de document."""
    url: str
    title: str
    text: str                        # contenu principal (markdown propre)
    pdf_bytes: bytes | None = None   # PDF brut si disponible
    source_type: str = "web"         # "web" | "wikipedia" | "calameo" | "tripadvisor" | "journal"
    metadata: dict = field(default_factory=dict)  # infos supplémentaires (langue, date, etc.)


class Fetcher:
    """Classe de base pour tous les handlers."""

    source_type: str = "web"

    def fetch(self, url: str) -> FetchResult:
        """Extraction + interprétation en une passe (comportement historique)."""
        raise NotImplementedError

    def can_handle(self, url: str) -> bool:
        raise NotImplementedError

    # ── Phase 1 : extraction brute ─────────────────────────────────────────────

    def extract_raw(self, url: str) -> "RawBundle":
        """
        Phase 1 : télécharge les artefacts bruts depuis le web et les sauvegarde
        dans fetcher_raw/{stem}/.

        Implémentation par défaut : appelle fetch() et sauvegarde le texte produit.
        Les handlers spécialisés (Calameo…) surchargent cette méthode pour sauvegarder
        des artefacts binaires (screenshots, images, PDF) avant tout traitement OCR.
        """
        from .stage import init_bundle, save_bundle
        from .output import _url_to_stem

        stem = _url_to_stem(url)
        bundle = init_bundle(url, stem, self.source_type)

        result = self.fetch(url)
        bundle.title = result.title
        bundle.metadata = result.metadata

        # Texte brut
        txt_path = bundle.dir / "raw_content.txt"
        txt_path.write_text(result.text, encoding="utf-8")
        bundle.raw_content_file = "raw_content.txt"

        # PDF si disponible
        if result.pdf_bytes:
            pdf_path = bundle.dir / "document.pdf"
            pdf_path.write_bytes(result.pdf_bytes)
            bundle.pdf_file = "document.pdf"

        save_bundle(bundle)
        print(f"  [extract] Bundle → {bundle.dir}")
        return bundle

    # ── Phase 2 : interprétation depuis le staging ─────────────────────────────

    def interpret(self, bundle: "RawBundle") -> FetchResult:
        """
        Phase 2 : lit les artefacts bruts depuis le staging et retourne un FetchResult.

        Implémentation par défaut : lit le texte sauvegardé par extract_raw().
        Les handlers spécialisés surchargent cette méthode (ex. Calameo → OCR).
        """
        text = ""
        pdf_bytes = None

        if bundle.raw_content_path and bundle.raw_content_path.exists():
            text = bundle.raw_content_path.read_text(encoding="utf-8")
        if bundle.pdf_path and bundle.pdf_path.exists():
            pdf_bytes = bundle.pdf_path.read_bytes()

        return FetchResult(
            url=bundle.url,
            title=bundle.title,
            text=text,
            pdf_bytes=pdf_bytes,
            source_type=bundle.source_type,
            metadata=bundle.metadata,
        )


class FetchError(Exception):
    """Erreur lors de la récupération d'une URL."""
