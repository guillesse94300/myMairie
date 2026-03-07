"""
fetcher/fetchers/journal.py — Handler sites de presse (Courrier Picard, Oise Hebdo…).

Stratégie en cascade :
1. curl_cffi : impersonation TLS Chrome → passe la plupart des 403
2. Playwright : rendu JS complet, accepte les cookies, scroll
3. Dégradation gracieuse : si paywall détecté → note explicite + ce qui est accessible

Pour ajouter un nouveau journal : ajouter son domaine dans JOURNAL_DOMAINS du dispatcher.
"""
from __future__ import annotations

import re
import time

from ..base import Fetcher, FetchError, FetchResult

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_TIMEOUT = 20
_PAYWALL_HINTS = [
    "abonnez-vous", "abonnement", "subscriber", "premium",
    "pour lire la suite", "accès réservé", "paywall",
    "connectez-vous pour lire",
]


class JournalFetcher(Fetcher):
    source_type = "journal"

    def can_handle(self, url: str) -> bool:
        return bool(re.search(r"(courrier-picard|oisehebdo)\.fr", url, re.IGNORECASE))

    def fetch(self, url: str) -> FetchResult:
        # — Tentative 1 : curl_cffi (rapide, contourne TLS anti-bot) —
        result = self._try_curl_cffi(url)
        if result:
            return result

        # — Tentative 2 : Playwright —
        result = self._try_playwright(url)
        if result:
            return result

        raise FetchError(f"Impossible de récupérer {url} (403 ou contenu vide)")

    # ── méthode 1 : curl_cffi ─────────────────────────────────────────────────

    def _try_curl_cffi(self, url: str) -> FetchResult | None:
        try:
            from curl_cffi import requests as curl_req
        except ImportError:
            print("  [journal] curl_cffi non disponible (pip install curl_cffi)")
            return None

        try:
            resp = curl_req.get(
                url,
                impersonate="chrome120",
                timeout=_TIMEOUT,
                headers={"Accept-Language": "fr-FR,fr;q=0.9"},
                allow_redirects=True,
            )
        except Exception as e:
            print(f"  [journal] curl_cffi erreur : {e}")
            return None

        if resp.status_code not in (200, 206):
            print(f"  [journal] curl_cffi HTTP {resp.status_code}")
            return None

        html = resp.text
        if len(html) < 500:
            print("  [journal] curl_cffi : contenu trop court")
            return None

        title, text = _parse_html(html, url)
        if not text:
            return None

        paywall_note = _paywall_note(text) if _is_paywalled(text) else ""
        return FetchResult(
            url=url,
            title=title,
            text=(text + paywall_note) if paywall_note else text,
            source_type=self.source_type,
            metadata={"method": "curl_cffi", "paywalled": bool(paywall_note)},
        )

    # ── méthode 2 : Playwright ────────────────────────────────────────────────

    def _try_playwright(self, url: str) -> FetchResult | None:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            print("  [journal] Playwright non disponible")
            return None

        html = ""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=_USER_AGENT,
                locale="fr-FR",
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9"},
            )
            page = ctx.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                _dismiss_popups(page)
                time.sleep(1.5)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.7)")
                time.sleep(1)
                html = page.content()
            except PWTimeout:
                print(f"  [journal] Playwright timeout pour {url}")
            except Exception as e:
                print(f"  [journal] Playwright erreur : {e}")
            finally:
                browser.close()

        if not html or len(html) < 500:
            return None

        title, text = _parse_html(html, url)
        if not text:
            return None

        paywall_note = _paywall_note(text) if _is_paywalled(text) else ""
        return FetchResult(
            url=url,
            title=title,
            text=(text + paywall_note) if paywall_note else text,
            source_type=self.source_type,
            metadata={"method": "playwright", "paywalled": bool(paywall_note)},
        )


# ── helpers HTML ───────────────────────────────────────────────────────────────

def _parse_html(html: str, url: str) -> tuple[str, str]:
    """Parse le HTML et retourne (titre, texte propre)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Titre
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.h1:
        title = soup.h1.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True).split("|")[0].strip()

    # Suppression des éléments parasites
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "form", ".cookie", "[class*='cookie']",
                     "[class*='banner']", "[class*='popup']"]):
        tag.decompose()

    # Contenu principal : préférer les balises sémantiques
    body = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=re.compile(r"(content|article|body|text)", re.I))
        or soup.find("body")
        or soup
    )

    raw = body.get_text(separator="\n", strip=True) if body else ""
    lines = [l.strip() for l in raw.splitlines() if l.strip() and len(l.strip()) > 3]
    text = "\n".join(lines)

    return title, text


def _is_paywalled(text: str) -> bool:
    low = text.lower()
    return any(hint in low for hint in _PAYWALL_HINTS)


def _paywall_note(text: str) -> str:
    return (
        "\n\n---\n\n"
        "_Note : ce contenu est partiellement ou totalement derrière un paywall. "
        "Seule la partie publiquement accessible a été indexée._"
    )


def _dismiss_popups(page) -> None:
    """Tente de fermer les popups cookies et RGPD courants."""
    for selector in [
        'button:has-text("Accepter")',
        'button:has-text("Tout accepter")',
        'button:has-text("J\'accepte")',
        "#onetrust-accept-btn-handler",
        '[class*="accept-all"]',
        '[id*="accept"]',
        ".didomi-continue-without-agreeing",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1_500):
                btn.click()
                return
        except Exception:
            continue
