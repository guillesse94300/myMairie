"""
fetcher/dispatcher.py — Route une URL vers le handler spécialisé approprié.

Règles évaluées dans l'ordre ; première correspondance gagne.
Pour ajouter un nouveau type de site : insérer une règle AVANT la règle ".*" finale.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Fetcher


# (pattern, module_path, class_name)
# Chargement paresseux pour éviter d'importer Playwright si pas nécessaire.
_RULES: list[tuple[str, str, str]] = [
    (r"wikipedia\.org/wiki/",                "fetcher.fetchers.wikipedia",   "WikipediaFetcher"),
    (r"calameo\.com/.*read/",                "fetcher.fetchers.calameo",     "CalameoFetcher"),
    (r"tripadvisor\.(fr|com|co\.\w+)/",      "fetcher.fetchers.tripadvisor", "TripAdvisorFetcher"),
    (r"(courrier-picard|oisehebdo)\.fr",     "fetcher.fetchers.journal",     "JournalFetcher"),
    (r".*",                                  "fetcher.fetchers.generic",     "GenericFetcher"),
]

_compiled: list[tuple[re.Pattern, str, str]] | None = None


def _get_rules():
    global _compiled
    if _compiled is None:
        _compiled = [(re.compile(pat, re.IGNORECASE), mod, cls) for pat, mod, cls in _RULES]
    return _compiled


def get_fetcher(url: str) -> "Fetcher":
    """Retourne une instance du handler approprié pour cette URL."""
    import importlib

    for pattern, module_path, class_name in _get_rules():
        if pattern.search(url):
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            return cls()

    # Ne devrait pas arriver (la règle ".*" est un catch-all)
    from .fetchers.generic import GenericFetcher
    return GenericFetcher()


def detect_type(url: str) -> str:
    """Retourne le nom du type détecté pour affichage/debug."""
    for pattern, _, class_name in _get_rules():
        if pattern.search(url):
            return class_name.replace("Fetcher", "").lower()
    return "generic"


# Mapping source_type → (module, class) pour la commande interpret
_TYPE_MAP: dict[str, tuple[str, str]] = {
    "calameo":    ("fetcher.fetchers.calameo",     "CalameoFetcher"),
    "wikipedia":  ("fetcher.fetchers.wikipedia",   "WikipediaFetcher"),
    "tripadvisor":("fetcher.fetchers.tripadvisor", "TripAdvisorFetcher"),
    "journal":    ("fetcher.fetchers.journal",     "JournalFetcher"),
    "web":        ("fetcher.fetchers.generic",     "GenericFetcher"),
}


def get_fetcher_for_type(source_type: str) -> "Fetcher":
    """Retourne une instance du handler associé à un source_type (utilisé par interpret)."""
    import importlib
    mod_path, cls_name = _TYPE_MAP.get(source_type, ("fetcher.fetchers.generic", "GenericFetcher"))
    module = importlib.import_module(mod_path)
    return getattr(module, cls_name)()
