"""
fetcher/fetchers/wikipedia.py — Handler Wikipedia via l'API MediaWiki.

Utilise l'API officielle (pas de scraping HTML) pour obtenir le texte propre.
Supporte wikipedia.fr, .en, etc. (détecte la langue depuis l'URL).
"""
from __future__ import annotations

import re
import urllib.parse

import requests

from ..base import Fetcher, FetchError, FetchResult

_API_URL = "https://{lang}.wikipedia.org/w/api.php"
_TIMEOUT = 15


class WikipediaFetcher(Fetcher):
    source_type = "wikipedia"

    def can_handle(self, url: str) -> bool:
        return bool(re.search(r"wikipedia\.org/wiki/", url, re.IGNORECASE))

    def fetch(self, url: str) -> FetchResult:
        lang, page_title = self._parse_url(url)
        api = _API_URL.format(lang=lang)

        # 1. Texte complet (section par section)
        params = {
            "action": "query",
            "titles": page_title,
            "prop": "extracts",
            "explaintext": True,      # texte brut, sans HTML
            "exsectionformat": "wiki", # titres de sections conservés
            "format": "json",
            "redirects": True,
        }
        resp = requests.get(api, params=params, timeout=_TIMEOUT,
                            headers={"User-Agent": "CasimirBot/1.0 (Pierrefonds mairie project)"})
        if resp.status_code != 200:
            raise FetchError(f"Wikipedia API HTTP {resp.status_code} pour {url}")

        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))

        if "missing" in page:
            raise FetchError(f"Page Wikipedia introuvable : {page_title}")

        title = page.get("title", page_title)
        extract = page.get("extract", "").strip()

        if not extract:
            raise FetchError(f"Contenu vide pour {url}")

        # 2. Mise en forme markdown : == Section == → ## Section
        text = self._wikisections_to_md(extract)

        return FetchResult(
            url=url,
            title=title,
            text=text,
            source_type=self.source_type,
            metadata={"lang": lang, "page_title": page_title},
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_url(url: str) -> tuple[str, str]:
        """Extrait (langue, titre) depuis une URL Wikipedia."""
        parsed = urllib.parse.urlparse(url)
        # langue : fr, en, de…
        lang = parsed.netloc.split(".")[0]
        # titre : tout ce qui suit /wiki/
        m = re.search(r"/wiki/(.+)", parsed.path)
        if not m:
            raise FetchError(f"URL Wikipedia invalide : {url}")
        page_title = urllib.parse.unquote(m.group(1))
        return lang, page_title

    @staticmethod
    def _wikisections_to_md(text: str) -> str:
        """Convertit les titres == Section == en ## Section (markdown)."""
        lines = []
        for line in text.splitlines():
            # === sous-section === → ###
            line = re.sub(r"^=== (.+) ===$", r"### \1", line)
            # == section == → ##
            line = re.sub(r"^== (.+) ==$", r"## \1", line)
            lines.append(line)
        return "\n".join(lines)
