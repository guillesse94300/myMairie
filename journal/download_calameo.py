#!/usr/bin/env python3
"""
Télécharge les publications Calaméo de la Mairie de Pierrefonds en PDF
en capturant chaque page via Playwright.
"""

import os
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from PIL import Image
import io

OUTPUT_DIR = Path(__file__).parent

BOOKS = [
    ("006550686aba49e6c4c27", "LECHO-01-decembre-2020", 16),
    ("00655068608bf6895018a", "LECHO-02-mai-2021",      24),
    ("0065506861e9058ab9e16", "LECHO-03-octobre-2021",  12),
    ("0065506861a1d2b8a515b", "LECHO-04-mars-2022",     16),
    ("00655068693dc2c99f306", "LECHO-05-aout-2022",     16),
    ("00655068683479084105c", "LECHO-06-novembre-2022", 16),
    ("0065506861a29f3963347", "LECHO-07-fevrier-2023",  16),
    ("006550686ef475cd0ecb6", "LECHO-08-aout-2023",     16),
    ("0065506864d5887422d6c", "LECHO-09-decembre-2023", 16),
    ("0065506868eba682f92a8", "LECHO-10-mai-2024",      16),
    ("006550686445af2ae1cf1", "LECHO-11-decembre-2024", 16),
    ("006550686ad5327aa54f3", "LECHO-12-avril-2025",    16),
    ("0065506861daa9cb0cb5f", "LECHO-13-septembre-2025",16),
]


def download_book(page, book_id, filename, num_pages):
    """Télécharge un livre Calaméo en capturant chaque page."""
    out_pdf = OUTPUT_DIR / f"{filename}.pdf"
    if out_pdf.exists():
        print(f"  Déjà téléchargé: {filename}.pdf")
        return True

    url = f"https://www.calameo.com/read/{book_id}"
    print(f"  Ouverture: {url}")

    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
        time.sleep(3)

        # Essayer de passer en mode pleine page / single page
        # Caler la fenêtre sur la taille du viewer
        page.set_viewport_size({"width": 1400, "height": 1000})
        time.sleep(2)

        # Chercher et cliquer sur le bouton de mode single-page si disponible
        try:
            page.click('button[title*="single"]', timeout=2000)
            time.sleep(1)
        except:
            pass

        # Récupérer le nombre réel de pages depuis le JS du viewer
        real_pages = page.evaluate("""
            () => {
                // Essayer différentes façons de lire le nombre de pages
                if (window.viewer && window.viewer.book) return window.viewer.book.nb_pages;
                if (window.BookData) return window.BookData.nb_pages;
                // Chercher dans le DOM
                const el = document.querySelector('.book-pages, [data-pages]');
                if (el) return parseInt(el.textContent || el.dataset.pages);
                return null;
            }
        """)

        if real_pages:
            num_pages = real_pages
            print(f"  Pages réelles depuis JS: {num_pages}")

        images = []
        current_page = 1

        # Naviguer page par page et capturer
        while current_page <= num_pages:
            print(f"  Capture page {current_page}/{num_pages}...")

            # Attendre que la page soit chargée
            time.sleep(1.5)

            # Prendre screenshot du viewer principal
            # Chercher l'élément canvas ou le conteneur principal
            viewer_el = None
            for selector in ['.viewer-content', '#book-reader', '.book-container',
                              'canvas', '#viewer', '.flipbook', 'article']:
                try:
                    el = page.query_selector(selector)
                    if el:
                        viewer_el = el
                        break
                except:
                    pass

            if viewer_el:
                screenshot = viewer_el.screenshot()
            else:
                screenshot = page.screenshot(full_page=False)

            img = Image.open(io.BytesIO(screenshot))
            images.append(img.convert('RGB'))

            # Passer à la page suivante
            if current_page < num_pages:
                page.keyboard.press('ArrowRight')
                time.sleep(0.5)
                # Aussi essayer le bouton next
                try:
                    page.click('button.next, .btn-next, [title*="next"], [title*="suivant"]',
                               timeout=1000)
                except:
                    pass
                time.sleep(1)

            current_page += 1

        if images:
            # Sauvegarder en PDF
            images[0].save(
                out_pdf,
                save_all=True,
                append_images=images[1:],
                format='PDF',
                resolution=150
            )
            print(f"  OK Sauvegarde: {filename}.pdf ({len(images)} pages)")
            return True
        else:
            print(f"  ECHEC Aucune image capturee pour {filename}")
            return False

    except Exception as e:
        print(f"  ERREUR pour {filename}: {e}")
        return False


def main():
    print("Telechargement des publications L'ECHO depuis Calameo")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            viewport={"width": 1400, "height": 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()

        success_count = 0
        for book_id, filename, num_pages in BOOKS:
            print(f"\nTraitement: {filename}")
            if download_book(page, book_id, filename, num_pages):
                success_count += 1
            time.sleep(2)

        browser.close()

    print(f"\n{'='*60}")
    print(f"Terminé: {success_count}/{len(BOOKS)} publications téléchargées")
    # Lister les fichiers créés
    pdfs = sorted(OUTPUT_DIR.glob("LECHO-*.pdf"))
    for pdf in pdfs:
        size_kb = pdf.stat().st_size // 1024
        print(f"  {pdf.name} ({size_kb} KB)")


if __name__ == "__main__":
    main()
