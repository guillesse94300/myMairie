"""
fetch_sites.py — Récupère le contenu des URLs listées dans site_url.txt (ou siteweb.txt)
et le stocke dans des fichiers .md pour enrichir la connaissance de Casimir.
Usage : python fetch_sites.py

Fallback : si une URL échoue (403, contenu vide), utilise un service de scraping
(ScraperAPI ou ZenRows) si la clé API est définie : SCRAPER_API_KEY ou ZENROWS_API_KEY
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Installez les dépendances : pip install requests beautifulsoup4")
    raise SystemExit(1)

try:
    from curl_cffi import requests as curl_requests
    _CURL_CFFI_OK = True
except ImportError:
    _CURL_CFFI_OK = False

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False

APP_DIR = Path(__file__).parent
# site_url.txt prioritaire, siteweb.txt en secours
SITE_URL_FILE = APP_DIR / "site_url.txt"
SITEWEB_FILE = APP_DIR / "siteweb.txt"
OUTPUT_DIR = APP_DIR / "knowledge_sites"
CHUNK_SIZE = 100_000  # max bytes à lire par page
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
# Sites protégés (403 avec requests) : utiliser curl_cffi qui imite le TLS de Chrome
# pip install curl_cffi
TLS_IMPERSONATE_DOMAINS = ("courrier-picard.fr",)
# Sites qui chargent le contenu en JS ou anti-bot strict : Playwright (navigateur headless)
# pip install playwright && playwright install chromium
JS_RENDER_DOMAINS = ("notion.site", "notion.so", "tripadvisor.fr")
# Sites à ignorer (403 / contenu inaccessible) : on ne tente pas
SKIP_DOMAINS = ("facebook.com",)
# Services de scraping en fallback (variable d'env : SCRAPER_API_KEY ou ZENROWS_API_KEY)
SCRAPERAPI_URL = "http://api.scraperapi.com/"
ZENROWS_URL = "https://api.zenrows.com/v1/"


def url_to_filename(url: str) -> str:
    """Génère un nom de fichier sûr à partir de l'URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "").replace(".", "_")
    path = parsed.path.strip("/").replace("/", "_")
    if not path:
        path = "index"
    # Limiter la longueur
    name = f"{domain}_{path}"[:80]
    # Nettoyer les caractères invalides
    name = re.sub(r"[^\w\-_]", "_", name)
    return f"{name}.md"


def extract_text(html: str, url: str) -> str:
    """Extrait le texte principal d'une page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    # Supprimer scripts, styles, nav répétitifs
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    body = soup.find("body") or soup
    if not body:
        return ""
    text = body.get_text(separator="\n", strip=True)
    # Nettoyer les lignes vides multiples
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n\n".join(lines)


def _needs_tls_impersonate(url: str) -> bool:
    """Sites qui renvoient 403 sans impersonation TLS (ex. courrier-picard)."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(d in domain for d in TLS_IMPERSONATE_DOMAINS)


def _needs_js_render(url: str) -> bool:
    """Sites qui chargent le contenu en JavaScript (ex. Notion)."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(d in domain for d in JS_RENDER_DOMAINS)


def _skip_domain(url: str) -> bool:
    """Sites à ignorer (évite 403 / message d'échec)."""
    domain = urlparse(url).netloc.lower().replace("www.", "")
    return any(d in domain for d in SKIP_DOMAINS)


def _fetch_with_requests(url: str, headers: dict) -> requests.Response:
    """Requête standard via requests."""
    return requests.get(url, timeout=TIMEOUT, headers=headers, stream=True)


def _fetch_with_curl_cffi(url: str) -> requests.Response:
    """Requête via curl_cffi (imite le TLS de Chrome, contourne le 403)."""
    return curl_requests.get(url, impersonate="chrome120", timeout=TIMEOUT)


def _get_scraper_api_key() -> str | None:
    """Clé API pour le fallback scraping (ScraperAPI prioritaire, sinon ZenRows)."""
    return os.environ.get("SCRAPER_API_KEY") or os.environ.get("ZENROWS_API_KEY") or None


def _fetch_with_scraping_api(url: str, api_key: str) -> str | None:
    """
    Récupère la page via un service de scraping (ScraperAPI ou ZenRows).
    ScraperAPI : SCRAPER_API_KEY -> http://api.scraperapi.com?api_key=...&url=...
    ZenRows   : ZENROWS_API_KEY   -> https://api.zenrows.com/v1/?apikey=...&url=...
    """
    try:
        if os.environ.get("SCRAPER_API_KEY"):
            # ScraperAPI : timeout 60s recommandé (ils retentent côté serveur)
            r = requests.get(
                SCRAPERAPI_URL,
                params={"api_key": api_key, "url": url},
                timeout=65,
            )
        else:
            # ZenRows
            r = requests.get(
                ZENROWS_URL,
                params={"apikey": api_key, "url": url},
                timeout=65,
            )
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _fetch_with_playwright(url: str) -> str | None:
    """Charge la page via Playwright (exécute le JS, pour Notion, TripAdvisor etc.)."""
    if not _PLAYWRIGHT_OK:
        return None
    try:
        with sync_playwright() as p:
            # Réduire la détection "headless" (surtout pour TripAdvisor)
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="fr-FR",
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()
            # Masquer webdriver (souvent détecté par les anti-bot)
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            # Accepter les cookies si un bouton apparaît
            try:
                accept_btn = page.get_by_role("button", name=re.compile(r"accepter|accept|ok|agree", re.I))
                if accept_btn.is_visible(timeout=3000):
                    accept_btn.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass
            html = page.content()
            # Si le body est quasi vide, utiliser le texte visible (Notion)
            try:
                visible = page.locator("body").inner_text(timeout=3000)
                if visible and len(visible.strip()) > 100:
                    html = f"<body><div>{visible}</div></body>"
            except Exception:
                pass
            browser.close()
            return html
    except Exception:
        return None


def fetch_url(url: str) -> tuple[str, str] | None:
    """Récupère une URL et retourne (titre, contenu_markdown) ou None."""
    if _skip_domain(url):
        return None  # ignorer sans tenter (évite 403 / message d'échec)
    html = None
    try:
        # Playwright en priorité pour Notion (contenu JS)
        if _needs_js_render(url) and _PLAYWRIGHT_OK:
            html = _fetch_with_playwright(url)
        if html is None and _needs_tls_impersonate(url) and _CURL_CFFI_OK:
            r = _fetch_with_curl_cffi(url)
            r.raise_for_status()
            html = r.text
        if html is None:
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            }
            if _needs_tls_impersonate(url) and _CURL_CFFI_OK:
                r = _fetch_with_curl_cffi(url)
            else:
                r = _fetch_with_requests(url, headers)
            r.raise_for_status()
            if hasattr(r, "apparent_encoding") and r.apparent_encoding:
                r.encoding = r.apparent_encoding
            elif not getattr(r, "encoding", None):
                r.encoding = "utf-8"
            if _needs_tls_impersonate(url) and _CURL_CFFI_OK:
                html = r.text
            else:
                html = ""
                for chunk in r.iter_content(chunk_size=8192, decode_unicode=True):
                    if chunk:
                        html += chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="replace")
                    if len(html) > CHUNK_SIZE:
                        break
        if not html:
            html = _try_scraping_api_fallback(url)
            if html:
                print(" (fallback scraping)", end="")
        if not html:
            return None
        text = extract_text(html, url)
        min_len = 50 if _needs_js_render(url) else 100
        if not text or len(text) < min_len:
            # Fallback : service de scraping (contenu vide ou page anti-bot)
            html = _try_scraping_api_fallback(url)
            if html:
                print(" (fallback scraping)", end="")
                text = extract_text(html, url)
        if not text or len(text) < min_len:
            return None
        # Titre depuis la page ou l'URL
        soup = BeautifulSoup(html[:5000], "html.parser")
        title_tag = soup.find("title")
        title = (title_tag.get_text(strip=True) if title_tag else url) or url
        md = f"# {title}\n\nSource : {url}\n\n---\n\n{text}"
        return (title, md)
    except Exception as e:
        # En cas d'exception, tenter le fallback scraping avant d'abandonner
        api_key = _get_scraper_api_key()
        if api_key:
            html = _fetch_with_scraping_api(url, api_key)
            if html:
                text = extract_text(html, url)
                if text and len(text) >= 50:
                    soup = BeautifulSoup(html[:5000], "html.parser")
                    title_tag = soup.find("title")
                    title = (title_tag.get_text(strip=True) if title_tag else url) or url
                    return (title, f"# {title}\n\nSource : {url}\n\n---\n\n{text}")
        print(f"    Erreur : {e}")
        return None


def _try_scraping_api_fallback(url: str) -> str | None:
    """Appelé quand la récupération directe échoue ; utilise ScraperAPI ou ZenRows si configuré."""
    api_key = _get_scraper_api_key()
    if not api_key:
        return None
    return _fetch_with_scraping_api(url, api_key)


def main():
    url_file = SITE_URL_FILE if SITE_URL_FILE.exists() else SITEWEB_FILE
    if not url_file.exists():
        print(f"Fichier introuvable : {SITE_URL_FILE} ou {SITEWEB_FILE}")
        print("Créez site_url.txt (ou siteweb.txt) avec une URL par ligne.")
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    urls = []
    with open(url_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls:
        print(f"Aucune URL trouvée dans {url_file.name}")
        return
    needs_curl = any(_needs_tls_impersonate(u) for u in urls)
    needs_playwright = any(_needs_js_render(u) for u in urls)
    if needs_curl and not _CURL_CFFI_OK:
        print("  [!] Pour courrier-picard.fr et sites protégés : pip install curl_cffi\n")
    if needs_playwright and not _PLAYWRIGHT_OK:
        print("  [!] Pour notion.site (contenu JS) : pip install playwright && playwright install chromium\n")
    print(f"Récupération de {len(urls)} URL(s)...\n")
    success = 0
    for i, url in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] {url[:60]}...", end=" ")
        if _skip_domain(url):
            print("ignoré (site bloquant)")
            continue
        result = fetch_url(url)
        if result:
            title, md = result
            fname = url_to_filename(url)
            out_path = OUTPUT_DIR / fname
            out_path.write_text(md, encoding="utf-8")
            print(f"OK -> {fname}")
            success += 1
        else:
            print("ÉCHEC")
        time.sleep(0.5)  # politesse
    print(f"\nTerminé : {success}/{len(urls)} pages sauvegardées dans '{OUTPUT_DIR}'")


if __name__ == "__main__":
    main()
