"""
fetcher/fetchers/tripadvisor.py — Handler TripAdvisor via Playwright.

Extrait : nom, description, adresse, note, catégories d'avis, liste des avis visibles.
TripAdvisor nécessite un rendu JavaScript complet et détecte les bots.
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


class TripAdvisorFetcher(Fetcher):
    source_type = "tripadvisor"

    def can_handle(self, url: str) -> bool:
        return bool(re.search(r"tripadvisor\.(fr|com|co\.\w+)/", url, re.IGNORECASE))

    def fetch(self, url: str) -> FetchResult:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            raise FetchError("Playwright requis : pip install playwright && playwright install chromium")

        title = ""
        sections: list[str] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="fr-FR",
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            )
            page = ctx.new_page()

            # Masquer webdriver
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
                time.sleep(2)

                # Accepter les cookies si popup présent
                _accept_cookies(page)
                time.sleep(1)

                title = _extract_title(page)
                sections = _extract_sections(page)

                # Scroll pour charger les avis
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                time.sleep(1.5)
                sections += _extract_reviews(page)

            except PWTimeout:
                raise FetchError(f"Timeout TripAdvisor pour {url}")
            except FetchError:
                raise
            except Exception as e:
                raise FetchError(f"Erreur Playwright TripAdvisor : {e}")
            finally:
                browser.close()

        if not sections:
            raise FetchError(f"Aucun contenu extrait de {url}")

        return FetchResult(
            url=url,
            title=title or "TripAdvisor",
            text="\n\n".join(sections),
            source_type=self.source_type,
        )


# ── helpers DOM ────────────────────────────────────────────────────────────────

def _accept_cookies(page) -> None:
    """Tente de fermer les popups cookies courants."""
    for selector in [
        "#onetrust-accept-btn-handler",
        'button[id*="accept"]',
        'button:has-text("Accepter")',
        'button:has-text("Accept")',
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2_000):
                btn.click()
                return
        except Exception:
            continue


def _extract_title(page) -> str:
    for selector in ["h1", '[data-automation="mainH1"]', ".HjBfq"]:
        try:
            el = page.locator(selector).first
            if el.is_visible(timeout=2_000):
                return el.inner_text().strip()
        except Exception:
            continue
    return page.title().split("|")[0].strip()


def _extract_sections(page) -> list[str]:
    sections: list[str] = []

    # Note globale
    for sel in ['[data-automation="reviewCountBubble"]', ".oETBfkHU", '[class*="rating"]']:
        try:
            note = page.locator(sel).first.inner_text(timeout=2_000).strip()
            if note:
                sections.append(f"**Note :** {note}")
                break
        except Exception:
            continue

    # Description / À propos
    for sel in [
        '[data-automation="aboutSection"]',
        ".pIRBV._T",
        '[class*="description"]',
        ".fIrGe._T",
    ]:
        try:
            desc = page.locator(sel).first.inner_text(timeout=2_000).strip()
            if desc and len(desc) > 30:
                sections.append(f"## Description\n\n{desc}")
                break
        except Exception:
            continue

    # Adresse
    for sel in ["[class*='address']", '[data-automation="location"]', ".aK.f"]:
        try:
            addr = page.locator(sel).first.inner_text(timeout=2_000).strip()
            if addr:
                sections.append(f"**Adresse :** {addr}")
                break
        except Exception:
            continue

    return sections


def _extract_reviews(page) -> list[str]:
    """Extrait les avis visibles sur la page."""
    reviews: list[str] = []
    try:
        # Différents sélecteurs selon les versions de la page TripAdvisor
        for sel in [
            '[data-automation="reviewCard"]',
            ".review-container",
            '[class*="reviewCard"]',
        ]:
            cards = page.locator(sel).all()
            if cards:
                for card in cards[:15]:
                    try:
                        text = card.inner_text(timeout=1_000).strip()
                        if text and len(text) > 20:
                            reviews.append(f"- {text[:400]}")
                    except Exception:
                        continue
                if reviews:
                    break
    except Exception:
        pass

    if reviews:
        return ["## Avis\n\n" + "\n".join(reviews)]
    return []
