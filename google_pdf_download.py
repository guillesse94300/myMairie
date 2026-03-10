# -*- coding: utf-8 -*-
# google_pdf_download.py -- Recherche DuckDuckGo HTML + telechargement des PDFs
import argparse, os, re, sys, time
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from curl_cffi import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Dependance manquante : {e}")
    raise SystemExit(1)

DDG_URL = "https://html.duckduckgo.com/html/"
DDG_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}
RESULTS_PER_PAGE = 30
DELAY_BETWEEN_PAGES = 2
DELAY_BETWEEN_DOWNLOADS = 1
DOWNLOAD_TIMEOUT = 60


def slugify(text, max_len=80):
    text = unquote(text)
    text = os.path.splitext(os.path.basename(text))[0]
    text = re.sub(r"[^\w\s\-]", " ", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len] if text else "document"


def extract_pdf_links_ddg(html):
    soup = BeautifulSoup(html, "html.parser")
    pdf_links = []
    seen_urls = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        real_url = href
        if "uddg=" in href:
            match = re.search(r"uddg=([^&]+)", href)
            if match:
                real_url = unquote(match.group(1))
        if ".pdf" not in real_url.lower():
            continue
        if "duckduckgo.com" in real_url:
            continue
        if real_url in seen_urls:
            continue
        seen_urls.add(real_url)
        title = a_tag.get_text(strip=True)[:80] or slugify(real_url)
        pdf_links.append({"url": real_url, "title": title})
    return pdf_links


def parse_next_form(html):
    """Extrait les parametres du formulaire Next depuis la page DDG."""
    soup = BeautifulSoup(html, "html.parser")
    for form in soup.find_all("form"):
        inputs = form.find_all("input")
        fields = {inp.get("name"): inp.get("value", "") for inp in inputs if inp.get("name")}
        if "vqd" in fields and "s" in fields:
            return fields
    return None


def search_ddg(query, page=0, next_form=None):
    """Interroge DuckDuckGo HTML. Retourne (html, next_form_fields)."""
    if page == 0:
        data = {"q": query, "kl": "fr-fr"}
    elif next_form:
        data = next_form
    else:
        return None, None
    try:
        resp = requests.post(DDG_URL, data=data, headers=DDG_HEADERS, impersonate="chrome", timeout=15)
        resp.raise_for_status()
        html = resp.text
        return html, parse_next_form(html)
    except Exception as e:
        print(f"  [ERREUR] Requete DuckDuckGo echouee : {e}")
        return None, None


def download_pdf(url, output_dir, index):
    filename = f"{index:03d}_{slugify(url)}.pdf"
    filepath = output_dir / filename
    if filepath.exists():
        print(f"  [SKIP] {filename} (deja existant)")
        return True
    try:
        resp = requests.get(url, headers=DDG_HEADERS, timeout=DOWNLOAD_TIMEOUT, impersonate="chrome", allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "").lower()
        content = resp.content
        if not content:
            print(f"  [SKIP] {filename} (contenu vide)")
            return False
        if "application/pdf" not in content_type and content[:5] != b"%PDF-":
            print(f"  [SKIP] {filename} (pas un PDF : {content_type})")
            return False
        filepath.write_bytes(content)
        print(f"  [OK]   {filename} ({filepath.stat().st_size / 1048576:.1f} Mo)")
        return True
    except Exception as e:
        print(f"  [FAIL] {filename} -- {e}")
        return False


def interactive_mode():
    print("=" * 57)
    print("  DUCKDUCKGO PDF DOWNLOADER")
    print("=" * 57)
    print()
    termes = input("  Termes de recherche : ").strip()
    if not termes:
        print("  Aucun terme. Arret.")
        input("  Appuyez sur Entree...")
        return None, None, None
    output = input("  Dossier de sortie [source/pdf] : ").strip() or "source/pdf"
    try:
        max_pages = int(input("  Nombre max de pages [3] : ").strip() or "3")
    except ValueError:
        max_pages = 3
    return termes.split(), output, max_pages


def main():
    if len(sys.argv) == 1:
        result = interactive_mode()
        if result[0] is None:
            return
        termes, output, max_pages = result
    else:
        parser = argparse.ArgumentParser(description="Recherche DuckDuckGo de PDFs.")
        parser.add_argument("termes", nargs="+")
        parser.add_argument("-o", "--output", default="source/pdf")
        parser.add_argument("--max-pages", type=int, default=3)
        args = parser.parse_args()
        termes, output, max_pages = args.termes, args.output, args.max_pages

    query = " ".join(termes) + " filetype:pdf"
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 57)
    print(f"  Recherche : {query}")
    print(f"  Dossier   : {output_dir.resolve()}")
    print(f"  Pages max : {max_pages}")
    print("=" * 57)
    print()

    all_links = []
    seen_urls = set()
    next_form = None
    for page_num in range(max_pages):
        print(f"-- Page {page_num + 1} --")
        html, next_form = search_ddg(query, page_num, next_form)
        if html is None:
            print("  Arret.")
            break
        new_links = [lnk for lnk in extract_pdf_links_ddg(html) if lnk["url"] not in seen_urls]
        for lnk in new_links:
            seen_urls.add(lnk["url"])
        if not new_links:
            print("  Aucun nouveau PDF sur cette page. Fin.")
            break
        if next_form is None and page_num < max_pages - 1:
            print("  Pas de page suivante disponible.")
            break
        print(f"  {len(new_links)} PDF(s) trouves :")
        for i, lnk in enumerate(new_links, 1):
            print(f"    {i}. {lnk[chr(116)+chr(105)+chr(116)+chr(108)+chr(101)][:55]}  [{urlparse(lnk[chr(117)+chr(114)+chr(108)]).netloc}]")
        all_links.extend(new_links)
        print()
        if page_num < max_pages - 1:
            time.sleep(DELAY_BETWEEN_PAGES)

    if not all_links:
        print("  Aucun PDF trouve.")
        if len(sys.argv) == 1:
            input("  Appuyez sur Entree...")
        return

    print(f"  {len(all_links)} PDF(s) a telecharger.")
    print()
    total_ok = total_skip = 0
    for i, lnk in enumerate(all_links, 1):
        ok = download_pdf(lnk["url"], output_dir, i)
        total_ok += ok
        total_skip += not ok
        time.sleep(DELAY_BETWEEN_DOWNLOADS)

    print()
    print("=" * 57)
    print("  RESUME FINAL")
    print("=" * 57)
    print(f"  PDFs trouves    : {len(all_links)}")
    print(f"  PDFs telecharges: {total_ok}")
    print(f"  PDFs ignores    : {total_skip}")
    print(f"  Dossier         : {output_dir.resolve()}")
    print("=" * 57)

    if len(sys.argv) == 1:
        print()
        input("  Appuyez sur Entree pour fermer...")


if __name__ == "__main__":
    main()
