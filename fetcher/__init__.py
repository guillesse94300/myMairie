"""
fetcher — Service d'acquisition de documents pour la base de connaissance Casimir.

Usage programmatique :
    from fetcher import fetch
    result = fetch("https://fr.wikipedia.org/wiki/Pierrefonds_(Oise)")
    print(result.title, result.text[:200])

    # Workflow découplé (extraction puis interprétation) :
    from fetcher import extract_raw, interpret_raw
    bundle = extract_raw("https://www.calameo.com/read/...")   # phase 1 → fetcher_raw/
    result = interpret_raw(bundle.stem)                         # phase 2 → FetchResult

Usage CLI :
    python -m fetcher <url>                       # extraction + interprétation
    python -m fetcher extract <url>               # phase 1 seulement
    python -m fetcher interpret [<stem>]          # phase 2 seulement
    python -m fetcher list                        # liste le staging
    python -m fetcher --file site_url.txt         # batch
"""
from .base import FetchResult, FetchError
from .dispatcher import get_fetcher, get_fetcher_for_type, detect_type
from .output import save
from .stage import RawBundle, load_bundle, list_stems


def fetch(url: str) -> FetchResult:
    """
    Récupère le contenu d'une URL via le handler approprié (extraction + interprétation).
    Lève FetchError en cas d'échec.
    """
    fetcher = get_fetcher(url)
    return fetcher.fetch(url)


def fetch_and_save(url: str, dry_run: bool = False) -> dict:
    """
    Récupère et persiste sur disque (.md + PDF si disponible).
    Retourne les chemins écrits.
    """
    result = fetch(url)
    paths = save(result, dry_run=dry_run)
    return {"result": result, "paths": paths}


def extract_raw(url: str) -> RawBundle:
    """
    Phase 1 : télécharge les artefacts bruts dans fetcher_raw/{stem}/ sans OCR ni traitement.
    Retourne le RawBundle correspondant (utilisable par interpret_raw).
    """
    fetcher = get_fetcher(url)
    return fetcher.extract_raw(url)


def interpret_raw(stem: str) -> FetchResult:
    """
    Phase 2 : lit les artefacts bruts depuis le staging, exécute OCR/traitement
    et retourne un FetchResult prêt à être sauvegardé.
    """
    bundle = load_bundle(stem)
    fetcher = get_fetcher_for_type(bundle.source_type)
    return fetcher.interpret(bundle)


__all__ = [
    "fetch", "fetch_and_save",
    "extract_raw", "interpret_raw",
    "FetchResult", "FetchError",
    "RawBundle", "load_bundle", "list_stems",
    "get_fetcher", "get_fetcher_for_type", "detect_type",
]
