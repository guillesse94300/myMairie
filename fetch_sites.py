"""
fetch_sites.py — Récupère le contenu des URLs listées dans site_url.txt (ou siteweb.txt)
et le stocke dans des fichiers .md pour enrichir la connaissance de Casimir.
Usage : python fetch_sites.py
"""
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

APP_DIR = Path(__file__).parent
# site_url.txt prioritaire, siteweb.txt en secours
SITE_URL_FILE = APP_DIR / "site_url.txt"
SITEWEB_FILE = APP_DIR / "siteweb.txt"
OUTPUT_DIR = APP_DIR / "knowledge_sites"
CHUNK_SIZE = 100_000  # max bytes à lire par page
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


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


def fetch_url(url: str) -> tuple[str, str] | None:
    """Récupère une URL et retourne (titre, contenu_markdown) ou None."""
    try:
        r = requests.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        html = ""
        for chunk in r.iter_content(chunk_size=8192, decode_unicode=True):
            if chunk:
                html += chunk if isinstance(chunk, str) else chunk.decode("utf-8", errors="replace")
            if len(html) > CHUNK_SIZE:
                break
        text = extract_text(html, url)
        if not text or len(text) < 100:
            return None
        # Titre depuis la page ou l'URL
        soup = BeautifulSoup(html[:5000], "html.parser")
        title_tag = soup.find("title")
        title = (title_tag.get_text(strip=True) if title_tag else url) or url
        md = f"# {title}\n\nSource : {url}\n\n---\n\n{text}"
        return (title, md)
    except Exception as e:
        print(f"    Erreur : {e}")
        return None


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
    print(f"Récupération de {len(urls)} URL(s)...\n")
    success = 0
    for i, url in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] {url[:60]}...", end=" ")
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
