"""
fetcher/fetchers/generic.py — Handler générique (fallback universel).

Reprend la logique de fetch_sites.py existant :
- requests standard
- fallback Playwright si le contenu est trop court ou vide
"""
from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from ..base import Fetcher, FetchError, FetchResult

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 15
_MIN_CONTENT_LEN = 300   # seuil sous lequel on tente Playwright


class GenericFetcher(Fetcher):
    source_type = "web"

    def can_handle(self, url: str) -> bool:
        return True  # catch-all

    def fetch(self, url: str) -> FetchResult:
        # — Tentative 1 : requests —
        result = self._try_requests(url)
        if result:
            return result

        # — Tentative 2 : Playwright —
        result = self._try_playwright(url)
        if result:
            return result

        raise FetchError(f"Impossible de récupérer {url}")

    # ── méthodes ───────────────────────────────────────────────────────────────

    def _try_requests(self, url: str) -> FetchResult | None:
        try:
            resp = requests.get(
                url,
                timeout=_TIMEOUT,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                },
                allow_redirects=True,
            )
        except requests.RequestException as e:
            print(f"  [generic] requests erreur : {e}")
            return None

        if resp.status_code != 200:
            print(f"  [generic] HTTP {resp.status_code}")
            return None

        html = resp.text

        # Anubis renvoie un HTTP 200 avec une page de challenge JS → fallback Playwright
        if "Anubis" in html or "workProof" in html:
            print("  [generic] Anubis détecté via requests, fallback Playwright")
            return None

        title, text = _extract(html, url)

        if not text or len(text) < _MIN_CONTENT_LEN:
            return None

        return FetchResult(url=url, title=title, text=text, source_type=self.source_type,
                           metadata={"method": "requests"})

    def _try_playwright(self, url: str) -> FetchResult | None:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            return None

        html = ""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=_USER_AGENT, locale="fr-FR")
            page = ctx.new_page()
            try:
                # "domcontentloaded" se déclenche dès que le DOM est parsé,
                # sans attendre la fin des requêtes réseau — indispensable quand
                # Anubis / un challenge JS maintient le réseau actif en permanence.
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                except PWTimeout:
                    print(f"  [generic] Playwright timeout (goto) pour {url}")
                    return None

                time.sleep(1.5)

                # — Détection Anubis (proof-of-work anti-bot) —
                # Anubis affiche un challenge JS puis redirige ; on attend qu'il passe.
                if _is_anubis_page(page):
                    print("  [generic] Anubis détecté, attente du challenge (≤60s)...")
                    for _ in range(60):
                        time.sleep(1)
                        if not _is_anubis_page(page):
                            print("  [generic] Anubis passé.")
                            # Attendre que la vraie page soit chargée après redirection
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=15_000)
                            except PWTimeout:
                                pass
                            time.sleep(1.5)
                            break
                    else:
                        print("  [generic] Anubis : challenge non résolu (timeout 60s)")

                # Accepter les cookies si présents
                for sel in ['button:has-text("Accepter")', "#onetrust-accept-btn-handler"]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=1_000):
                            btn.click()
                            time.sleep(0.5)
                            break
                    except Exception:
                        continue
                html = page.content()
            except PWTimeout:
                print(f"  [generic] Playwright timeout pour {url}")
            except Exception as e:
                print(f"  [generic] Playwright erreur : {e}")
            finally:
                browser.close()

        if not html:
            return None

        title, text = _extract(html, url)
        if not text:
            return None

        return FetchResult(url=url, title=title, text=text, source_type=self.source_type,
                           metadata={"method": "playwright"})


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_anubis_page(page) -> bool:
    """Détecte si la page est une page de challenge Anubis (proof-of-work anti-bot)."""
    try:
        text = page.evaluate("() => document.body?.innerText || ''")
        return "Anubis" in text or "Vérification que vous n'êtes pas un robot" in text
    except Exception:
        return False


def _extract(html: str, url: str) -> tuple[str, str]:
    """Extrait titre et texte propre d'une page HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Titre
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.h1:
        title = soup.h1.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True).split("|")[0].strip()

    # Suppression éléments parasites
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    body = soup.find("body") or soup
    raw = body.get_text(separator="\n", strip=True)

    lines = [l.strip() for l in raw.splitlines() if l.strip() and len(l.strip()) > 3]
    # Dédupliquer les lignes consécutives identiques
    deduped = []
    prev = None
    for l in lines:
        if l != prev:
            deduped.append(l)
        prev = l

    return title, "\n".join(deduped)
