"""
fetcher/fetchers/calameo.py — Handler Calameo.

Stratégie :
1. Tente un téléchargement PDF direct (/download/{code}).
2. Si échec → Playwright : navigue le viewer page par page, extrait le texte
   via l'accessibilité DOM ou les éléments texte du canvas.
3. Sortie : texte → .md  +  PDF → static/ (si téléchargé).
"""
from __future__ import annotations

import io
import re
import time
from pathlib import Path

import requests

from ..base import Fetcher, FetchError, FetchResult

_TIMEOUT = 20
_DOWNLOAD_URL = "https://www.calameo.com/download/{code}"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class CalameoFetcher(Fetcher):
    source_type = "calameo"

    def can_handle(self, url: str) -> bool:
        return bool(re.search(r"calameo\.com/.*read/", url, re.IGNORECASE))

    def fetch(self, url: str) -> FetchResult:
        code = self._extract_code(url)

        # — Étape 1 : API Calameo → titre + métadonnées —
        api_title, _, api_meta = self._fetch_api(code)

        # — Étape 2 : téléchargement PDF direct (quand disponible) —
        pdf_bytes = self._try_download_pdf(code)
        pdf_text = self._text_from_pdf(pdf_bytes) if pdf_bytes else ""

        # — Étape 3 : Playwright → screenshots de chaque page + OCR —
        pw_title, pw_text, screenshot_images, built_pdf = self._screenshot_pages(url, code)
        # Si pas de PDF encore, on utilise celui construit depuis les screenshots
        if not pdf_bytes and built_pdf:
            pdf_bytes = built_pdf

        # — Étape 4 : fallback CDN thumbnails + OCR (basse résolution) —
        cdn_ocr = ""
        if not pw_text and not pdf_text and api_meta.get("image_key"):
            print(f"  [calameo] Fallback CDN thumbnails + OCR...")
            cdn_images, cdn_pdf = self._download_pages_as_pdf(api_meta["image_key"])
            if cdn_images:
                cdn_ocr = _ocr_images(cdn_images)
                if not pdf_bytes and cdn_pdf:
                    pdf_bytes = cdn_pdf

        title = pw_title or api_title or f"Publication Calameo {code}"
        text = pw_text or pdf_text or cdn_ocr

        if not text:
            lines = [f"Document Calameo — {title}", ""]
            if api_meta.get("author"):
                lines.append(f"Auteur / éditeur : {api_meta['author']}")
            if api_meta.get("date"):
                lines.append(f"Date de publication : {api_meta['date']}")
            lines += [
                "",
                "_Le contenu est rendu sous forme d'images. "
                "OCR non disponible (installez pytesseract ou easyocr)._",
            ]
            text = "\n".join(lines)

        return FetchResult(
            url=url,
            title=title,
            text=text,
            pdf_bytes=pdf_bytes,
            source_type=self.source_type,
            metadata={"calameo_code": code, **api_meta},
        )

    # ── Screenshots Playwright + OCR ──────────────────────────────────────────

    @staticmethod
    def _screenshot_pages(url: str, code: str) -> tuple[str, str, list, bytes]:
        """
        Ouvre le viewer Calameo avec Playwright, prend un screenshot par page,
        OCR chaque screenshot, assemble un PDF.
        Retourne (title, texte_ocr, liste_images_PIL, pdf_bytes).
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
            from PIL import Image
        except ImportError:
            return "", "", [], b""

        title = ""
        images: list = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1400, "height": 900},
                device_scale_factor=2,   # résolution 2× → meilleur OCR
            )
            page = ctx.new_page()

            try:
                # Bloquer CookieBot et trackers pour éviter la popup de consentement
                def _block_trackers(route):
                    u = route.request.url
                    if any(d in u for d in ("cookiebot.com", "consentcdn", "gimii.fr",
                                            "doubleclick", "googlesyndication")):
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", _block_trackers)

                page.goto(url, wait_until="networkidle", timeout=45_000)
                time.sleep(4)

                # Attendre le chargement du viewer (canvas ou SVG)
                time.sleep(3)
                title = page.title().split("|")[0].strip()

                # Détecter le nombre de pages
                nb_pages = _detect_page_count(page)
                if nb_pages <= 1:
                    # Essai depuis le texte de compteur
                    try:
                        import re as _re
                        body_text = page.evaluate("() => document.body.innerText")
                        m = _re.search(r"(\d+)\s*/\s*(\d+)", body_text)
                        if m:
                            nb_pages = int(m.group(2))
                    except Exception:
                        pass

                print(f"  [calameo] {nb_pages} pages, capture écran + OCR...")

                for i in range(min(nb_pages, 100)):
                    time.sleep(1.0)
                    # Capture de la page entière (le viewer occupe la majorité)
                    png = page.screenshot(full_page=False)
                    img = Image.open(io.BytesIO(png)).convert("RGB")
                    # Rogner les bords de navigation (haut/bas ~10%)
                    w, h = img.size
                    margin = int(h * 0.08)
                    img = img.crop((0, margin, w, h - margin))
                    images.append(img)

                    if i < nb_pages - 1:
                        page.keyboard.press("ArrowRight")

            except PWTimeout:
                print(f"  [calameo] Timeout screenshot pour {url}")
            except Exception as e:
                print(f"  [calameo] Erreur screenshot : {e}")
            finally:
                browser.close()

        if not images:
            return title, "", [], b""

        # OCR sur les screenshots
        ocr_text = _ocr_images(images)

        # Assembler PDF depuis les screenshots
        pdf_bytes = b""
        try:
            pdf_buf = io.BytesIO()
            images[0].save(pdf_buf, format="PDF", save_all=True,
                           append_images=images[1:], resolution=96)
            pdf_bytes = pdf_buf.getvalue()
            print(f"  [calameo] PDF assemblé depuis {len(images)} screenshots")
        except Exception as e:
            print(f"  [calameo] Assemblage PDF échoué : {e}")

        return title, ocr_text, images, pdf_bytes

    # ── Téléchargement pages + PDF ────────────────────────────────────────────

    @staticmethod
    def _download_pages_as_pdf(image_key: str) -> tuple[list, bytes]:
        """
        Télécharge les pages JPEG depuis le CDN Calameo et les assemble en PDF.
        URL pattern : https://i.calameoassets.com/{key}/p{n}.jpg
        S'arrête à la première 404.
        Retourne (liste_images_PIL, pdf_bytes).
        """
        try:
            from PIL import Image
        except ImportError:
            print("  [calameo] Pillow requis pour l'assemblage PDF (pip install Pillow)")
            return [], b""

        base = f"https://i.calameoassets.com/{image_key}"
        images: list = []

        for n in range(1, 201):  # max 200 pages
            img_url = f"{base}/p{n}.jpg"
            try:
                resp = requests.get(img_url, timeout=_TIMEOUT,
                                    headers={"User-Agent": _USER_AGENT})
                if resp.status_code == 404:
                    break
                if resp.status_code != 200:
                    print(f"  [calameo] page {n} HTTP {resp.status_code}, on s'arrête")
                    break
                img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                images.append(img)
                print(f"  [calameo] page {n} téléchargée ({img.width}×{img.height})")
            except Exception as e:
                print(f"  [calameo] page {n} erreur : {e}")
                break

        if not images:
            return [], b""

        print(f"  [calameo] {len(images)} pages téléchargées, assemblage PDF...")
        pdf_buf = io.BytesIO()
        images[0].save(
            pdf_buf,
            format="PDF",
            save_all=True,
            append_images=images[1:],
            resolution=150,
        )
        return images, pdf_buf.getvalue()

    # ── API Calameo ────────────────────────────────────────────────────────────

    @staticmethod
    def _fetch_api(code: str) -> tuple[str, str, dict]:
        """
        Appelle l'API interne Calameo pour récupérer les métadonnées.
        Endpoint : https://d.calameo.com/pinwheel/viewer/book/get?bkcode={code}
        """
        api_url = f"https://d.calameo.com/pinwheel/viewer/book/get?bkcode={code}"
        try:
            resp = requests.get(api_url, timeout=_TIMEOUT,
                                headers={"User-Agent": _USER_AGENT,
                                         "Referer": f"https://www.calameo.com/read/{code}"})
            if resp.status_code != 200:
                return "", "", {}
            data = resp.json()
            content = data.get("content", {})
            title = content.get("name") or content.get("title") or ""
            # Date de publication (timestamp Unix)
            pub_ts = content.get("publication")
            pub_date = ""
            if pub_ts:
                from datetime import datetime, timezone
                pub_date = datetime.fromtimestamp(pub_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            # Compte auteur
            account = content.get("account", {})
            author = account.get("name", "")
            # URL image première page (pour référence)
            img_key = content.get("key", "")
            img_url = f"https://i.calameoassets.com/{img_key}/p1.jpg" if img_key else ""
            meta = {
                "date": pub_date,
                "author": author,
                "image_key": img_key,
                "cover_url": img_url,
            }
            # Pas de description texte dans cette API → texte vide
            print(f"  [calameo] API : titre={title!r}, auteur={author!r}, date={pub_date}")
            return title, "", meta
        except Exception as e:
            print(f"  [calameo] API directe échouée : {e}")
            return "", "", {}

    # ── Phase 1 : extraction brute (sans OCR) ─────────────────────────────────

    def extract_raw(self, url: str) -> "RawBundle":
        """
        Télécharge les artefacts bruts (API meta, PDF direct, screenshots, CDN images)
        et les sauvegarde dans fetcher_raw/{stem}/ SANS faire d'OCR.
        Retourne un RawBundle prêt pour interpret().
        """
        from ..stage import init_bundle, save_bundle
        from ..output import _url_to_stem

        code = self._extract_code(url)
        stem = _url_to_stem(url)
        bundle = init_bundle(url, stem, self.source_type)

        # — Métadonnées API —
        api_title, _, api_meta = self._fetch_api(code)
        bundle.title = api_title
        bundle.metadata = {"calameo_code": code, **api_meta}

        # — PDF direct —
        pdf_bytes = self._try_download_pdf(code)
        if pdf_bytes:
            pdf_path = bundle.dir / "document.pdf"
            pdf_path.write_bytes(pdf_bytes)
            bundle.pdf_file = "document.pdf"
            print(f"  [extract] PDF direct sauvé ({len(pdf_bytes):,} octets)")

        # — Screenshots Playwright (sans OCR) —
        screenshot_files = self._screenshot_pages_raw(url, bundle.dir)
        bundle.screenshot_files = screenshot_files

        # — CDN thumbnails (fallback si pas de screenshots) —
        if not screenshot_files and api_meta.get("image_key"):
            cdn_files = self._download_cdn_images(api_meta["image_key"], bundle.dir)
            bundle.cdn_image_files = cdn_files

        save_bundle(bundle)
        nb = len(bundle.screenshot_files) + len(bundle.cdn_image_files)
        print(f"  [extract] {nb} image(s) sauvée(s) → {bundle.dir}")
        return bundle

    # ── Phase 2 : interprétation depuis le staging ─────────────────────────────

    def interpret(self, bundle: "RawBundle") -> FetchResult:
        """
        Lit les artefacts bruts du staging, exécute l'OCR et retourne un FetchResult.
        Peut être relancé sans re-télécharger depuis le web.
        """
        try:
            from PIL import Image
        except ImportError:
            Image = None

        pdf_bytes: bytes | None = None
        pdf_text = ""
        ocr_text = ""

        # — Texte depuis PDF direct —
        if bundle.pdf_path and bundle.pdf_path.exists():
            pdf_bytes = bundle.pdf_path.read_bytes()
            pdf_text = self._text_from_pdf(pdf_bytes)
            print(f"  [interpret] PDF lu ({len(pdf_bytes):,} octets)")

        # — OCR sur les screenshots —
        if bundle.screenshot_files and Image:
            images = []
            for f in bundle.screenshot_files:
                p = bundle.dir / f
                if p.exists():
                    images.append(Image.open(p).convert("RGB"))
            if images:
                ocr_text = _ocr_images(images)
                print(f"  [interpret] OCR screenshots : {len(ocr_text)} chars")
                # PDF assemblé depuis les screenshots si pas de PDF direct
                if not pdf_bytes:
                    try:
                        import io as _io
                        buf = _io.BytesIO()
                        images[0].save(buf, format="PDF", save_all=True,
                                       append_images=images[1:], resolution=96)
                        pdf_bytes = buf.getvalue()
                        print(f"  [interpret] PDF assemblé depuis {len(images)} screenshots")
                    except Exception as e:
                        print(f"  [interpret] Assemblage PDF échoué : {e}")

        # — OCR sur les thumbnails CDN (fallback basse résolution) —
        elif bundle.cdn_image_files and Image and not ocr_text and not pdf_text:
            images = []
            for f in bundle.cdn_image_files:
                p = bundle.dir / f
                if p.exists():
                    images.append(Image.open(p).convert("RGB"))
            if images:
                ocr_text = _ocr_images(images)
                print(f"  [interpret] OCR CDN thumbnails : {len(ocr_text)} chars")

        code = bundle.metadata.get("calameo_code", "")
        title = bundle.title or f"Publication Calameo {code}"
        text = ocr_text or pdf_text

        if not text:
            lines = [f"Document Calameo — {title}", ""]
            if bundle.metadata.get("author"):
                lines.append(f"Auteur / éditeur : {bundle.metadata['author']}")
            if bundle.metadata.get("date"):
                lines.append(f"Date de publication : {bundle.metadata['date']}")
            lines += [
                "",
                "_Le contenu est rendu sous forme d'images. "
                "OCR non disponible (installez pytesseract ou easyocr)._",
            ]
            text = "\n".join(lines)

        return FetchResult(
            url=bundle.url,
            title=title,
            text=text,
            pdf_bytes=pdf_bytes,
            source_type=self.source_type,
            metadata=bundle.metadata,
        )

    # ── Screenshots sans OCR ───────────────────────────────────────────────────

    @staticmethod
    def _screenshot_pages_raw(url: str, out_dir: "Path") -> list[str]:
        """
        Ouvre le viewer Calameo, prend un screenshot par page et les sauvegarde
        en PNG dans out_dir (screenshot_001.png, …).
        Retourne la liste des noms de fichiers créés.
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
            from PIL import Image
        except ImportError:
            return []

        import io as _io
        saved: list[str] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1400, "height": 900},
                device_scale_factor=2,   # résolution 2× → meilleur OCR
            )
            page = ctx.new_page()

            try:
                def _block_trackers(route):
                    u = route.request.url
                    if any(d in u for d in ("cookiebot.com", "consentcdn", "gimii.fr",
                                            "doubleclick", "googlesyndication")):
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", _block_trackers)
                page.goto(url, wait_until="networkidle", timeout=45_000)
                time.sleep(4)

                nb_pages = _detect_page_count(page)
                if nb_pages <= 1:
                    try:
                        import re as _re
                        body_text = page.evaluate("() => document.body.innerText")
                        m = _re.search(r"(\d+)\s*/\s*(\d+)", body_text)
                        if m:
                            nb_pages = int(m.group(2))
                    except Exception:
                        pass

                print(f"  [extract] {nb_pages} page(s), capture PNG...")

                for i in range(min(nb_pages, 100)):
                    time.sleep(1.0)
                    png = page.screenshot(full_page=False)
                    img = Image.open(_io.BytesIO(png)).convert("RGB")
                    w, h = img.size
                    margin = int(h * 0.08)
                    img = img.crop((0, margin, w, h - margin))

                    fname = f"screenshot_{i + 1:03d}.png"
                    img.save(out_dir / fname, format="PNG")
                    saved.append(fname)

                    if i < nb_pages - 1:
                        page.keyboard.press("ArrowRight")

            except PWTimeout:
                print(f"  [extract] Timeout screenshot pour {url}")
            except Exception as e:
                print(f"  [extract] Erreur screenshot : {e}")
            finally:
                browser.close()

        return saved

    # ── CDN thumbnails sans OCR ────────────────────────────────────────────────

    @staticmethod
    def _download_cdn_images(image_key: str, out_dir: "Path") -> list[str]:
        """
        Télécharge les pages JPEG depuis le CDN Calameo et les sauvegarde dans out_dir.
        Retourne la liste des noms de fichiers créés.
        """
        try:
            from PIL import Image
        except ImportError:
            return []

        import io as _io
        base = f"https://i.calameoassets.com/{image_key}"
        saved: list[str] = []

        for n in range(1, 201):
            img_url = f"{base}/p{n}.jpg"
            try:
                resp = requests.get(img_url, timeout=_TIMEOUT,
                                    headers={"User-Agent": _USER_AGENT})
                if resp.status_code == 404:
                    break
                if resp.status_code != 200:
                    break
                img = Image.open(_io.BytesIO(resp.content)).convert("RGB")
                fname = f"page_{n:03d}.jpg"
                img.save(out_dir / fname, format="JPEG")
                saved.append(fname)
                print(f"  [extract] CDN page {n} ({img.width}×{img.height})")
            except Exception as e:
                print(f"  [extract] CDN page {n} erreur : {e}")
                break

        return saved

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_code(url: str) -> str:
        m = re.search(r"/read/([a-zA-Z0-9]+)", url)
        if not m:
            raise FetchError(f"Code Calameo introuvable dans : {url}")
        return m.group(1)

    def _try_download_pdf(self, code: str) -> bytes | None:
        """Tente le téléchargement PDF direct. Retourne bytes ou None."""
        dl_url = _DOWNLOAD_URL.format(code=code)
        try:
            resp = requests.get(dl_url, timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT},
                                allow_redirects=True)
            ct = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and "pdf" in ct:
                print(f"  [calameo] PDF téléchargé directement ({len(resp.content)} octets)")
                return resp.content
        except requests.RequestException as e:
            print(f"  [calameo] Téléchargement direct échoué : {e}")
        return None

    @staticmethod
    def _extract_text_playwright(url: str, code: str) -> tuple[str, str]:
        """Utilise Playwright pour extraire le texte du viewer Calameo."""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            print("  [calameo] Playwright non disponible (pip install playwright && playwright install chromium)")
            return "", ""

        title = ""
        pages_text: list[str] = []
        # Capture des réponses réseau contenant du texte (JSON de pages)
        captured_json: list[str] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()

            # Intercepter les réponses réseau pour capturer les données de pages
            def _on_response(response):
                ct = response.headers.get("content-type", "")
                if ("json" in ct or "javascript" in ct) and response.status == 200:
                    try:
                        body = response.text()
                        if len(body) > 100:
                            captured_json.append(body)
                    except Exception:
                        pass

            page.on("response", _on_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=40_000)

                # — Fermer le bandeau de consentement (Deny suffit pour accéder au contenu) —
                _dismiss_consent(page)
                time.sleep(3)

                page.wait_for_load_state("networkidle", timeout=20_000)
                time.sleep(2)

                title = page.title().split("|")[0].strip()

                # — Tentative 1 : texte depuis les réponses réseau capturées —
                text_from_network = _text_from_captured_json(captured_json)
                if text_from_network:
                    print(f"  [calameo] Texte extrait depuis réponses réseau")
                    return title, text_from_network

                # — Tentative 2 : SVG <text> dans la page principale —
                page_text = _extract_svg_text(page)
                if page_text:
                    print(f"  [calameo] Texte extrait depuis SVG page principale")
                    return title, page_text

                # — Tentative 3 : chercher dans les iframes —
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    if any(s in frame.url for s in ("cookiebot", "consent", "about:blank")):
                        continue
                    frame_text = _extract_svg_text_from_frame(frame)
                    if frame_text:
                        print(f"  [calameo] Texte extrait depuis iframe {frame.url[:60]}")
                        return title, frame_text

                # — Tentative 4 : navigation page par page avec SVG —
                nb_pages = _detect_page_count(page)
                print(f"  [calameo] {nb_pages} pages détectées, navigation manuelle")
                for i in range(min(nb_pages, 50)):  # max 50 pages
                    pt = _extract_svg_text(page)
                    if pt:
                        pages_text.append(f"— Page {i + 1} —\n{pt}")
                    if i < nb_pages - 1:
                        page.keyboard.press("ArrowRight")
                        time.sleep(1.2)

            except PWTimeout:
                print(f"  [calameo] Timeout Playwright pour {url}")
            except Exception as e:
                print(f"  [calameo] Erreur Playwright : {e}")
            finally:
                browser.close()

        return title, "\n\n".join(pages_text)

    @staticmethod
    def _text_from_pdf(pdf_bytes: bytes) -> str:
        """Extrait le texte d'un PDF avec pdfplumber."""
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for p in pdf.pages:
                    t = p.extract_text()
                    if t:
                        text_parts.append(t.strip())
            return "\n\n".join(text_parts)
        except Exception as e:
            print(f"  [calameo] pdfplumber échoué : {e}")
            return ""


# ── fonctions Playwright helpers ───────────────────────────────────────────────

def _detect_page_count(page) -> int:
    """Détecte le nombre de pages depuis le DOM ou le texte du compteur."""
    try:
        count = page.evaluate("""
            () => {
                // Variables JS connues du viewer Calameo
                const candidates = [
                    window.Book?.TotalPages,
                    window.CALAMEO?.book?.pages,
                    window.calameo?.publication?.pages_count,
                    window.__INITIAL_STATE__?.publication?.pages,
                ];
                for (const c of candidates) {
                    if (c && typeof c === 'number' && c > 0) return c;
                }
                // Attributs data-*
                const el = document.querySelector('[data-total-pages],[data-pages]');
                if (el) {
                    const v = el.dataset.totalPages || el.dataset.pages;
                    if (v) return parseInt(v);
                }
                // Texte du compteur "Page X / Y" ou "X / Y"
                const counterText = document.body.innerText;
                const m = counterText.match(/\\d+\\s*\\/\\s*(\\d+)/);
                if (m) return parseInt(m[1]);
                return null;
            }
        """)
        if count and isinstance(count, (int, float)) and count > 0:
            return int(count)
    except Exception:
        pass
    return 1


def _extract_svg_text(page) -> str:
    """Extrait le texte depuis les éléments SVG <text> de la page principale."""
    try:
        text = page.evaluate("""
            () => {
                // SVG <text> — rendu principal du viewer Calameo
                const svgTexts = document.querySelectorAll('svg text, svg tspan');
                if (svgTexts.length > 0) {
                    return Array.from(svgTexts)
                        .map(e => e.textContent.trim())
                        .filter(t => t.length > 0)
                        .join(' ');
                }
                // Spans de couche texte PDF-style
                const spans = document.querySelectorAll('.text-layer span, [class*="textLayer"] span');
                if (spans.length > 0) {
                    return Array.from(spans).map(e => e.textContent).join(' ');
                }
                return '';
            }
        """)
        if text and len(text.strip()) > 20:
            lines = [l.strip() for l in text.split("  ") if l.strip()]
            return "\n".join(lines)
    except Exception:
        pass
    return ""


def _extract_svg_text_from_frame(frame) -> str:
    """Extrait le texte SVG depuis une iframe."""
    try:
        text = frame.evaluate("""
            () => {
                const svgTexts = document.querySelectorAll('svg text, svg tspan');
                if (svgTexts.length > 0) {
                    return Array.from(svgTexts)
                        .map(e => e.textContent.trim())
                        .filter(t => t.length > 0)
                        .join(' ');
                }
                return '';
            }
        """)
        if text and len(text.strip()) > 20:
            return text.strip()
    except Exception:
        pass
    return ""


def _text_from_captured_json(bodies: list[str]) -> str:
    """
    Tente d'extraire du texte lisible depuis les réponses JSON capturées.
    Calameo charge parfois les données de pages sous forme JSON.
    """
    import json
    collected: list[str] = []

    for body in bodies:
        body = body.strip()
        # Ignorer les petits fichiers et les scripts JS
        if len(body) < 200 or body.startswith("!function") or body.startswith("(function"):
            continue
        try:
            data = json.loads(body)
            _walk_json(data, collected)
        except (json.JSONDecodeError, ValueError):
            pass

    if not collected:
        return ""
    return "\n".join(collected)


def _preprocess_for_ocr(img):
    """
    Prétraitement d'une image PIL avant OCR :
    - conversion en niveaux de gris
    - amélioration du contraste
    - accentuation de la netteté
    - agrandissement si la largeur est inférieure à 2 000 px
    Retourne une image PIL en niveaux de gris, prête pour l'OCR.
    """
    from PIL import ImageEnhance, ImageFilter

    # Niveaux de gris
    gray = img.convert("L")

    # Contraste × 2
    gray = ImageEnhance.Contrast(gray).enhance(2.0)

    # Netteté
    gray = gray.filter(ImageFilter.SHARPEN)

    # Agrandissement minimal (l'OCR est meilleur au-dessus de ~2 000 px)
    w, h = gray.size
    if w < 2000:
        scale = 2000 / w
        new_w, new_h = int(w * scale), int(h * scale)
        from PIL import Image as _Image
        gray = gray.resize((new_w, new_h), _Image.LANCZOS)

    return gray


def _ocr_images(images: list) -> str:
    """
    OCR sur une liste d'images PIL avec prétraitement.

    Stratégie :
    1. Tesseract (fra+eng, PSM 6 « bloc de texte unifié ») → meilleur sur documents imprimés.
    2. EasyOCR (fr+en) → meilleur sur texte stylisé / coloré.
    Si les deux sont disponibles, on garde le résultat le plus long.
    """
    if not images:
        return ""

    preprocessed = [_preprocess_for_ocr(img) for img in images]

    tess_result = _ocr_tesseract(preprocessed)
    easy_result = _ocr_easyocr(images)       # EasyOCR préfère l'image couleur

    # Prendre le résultat le plus riche
    if tess_result and easy_result:
        best = tess_result if len(tess_result) >= len(easy_result) else easy_result
        engine = "Tesseract" if best is tess_result else "EasyOCR"
        print(f"  [calameo] OCR {engine} retenu : {len(best)} chars "
              f"(Tesseract={len(tess_result)}, EasyOCR={len(easy_result)})")
        return best
    result = tess_result or easy_result
    if result:
        return result

    print("  [calameo] Aucun moteur OCR disponible (pip install pytesseract ou easyocr)")
    return ""


def _ocr_tesseract(images: list) -> str:
    """OCR Tesseract avec PSM 6 (bloc unifié) et DPI 300."""
    try:
        import pytesseract
    except ImportError:
        return ""

    parts: list[str] = []
    config = "--oem 3 --psm 6 --dpi 300"
    for i, img in enumerate(images, 1):
        try:
            text = pytesseract.image_to_string(img, lang="fra+eng", config=config).strip()
            if text:
                parts.append(f"— Page {i} —\n{text}")
        except Exception as e:
            print(f"  [calameo] Tesseract page {i} erreur : {e}")

    if parts:
        result = "\n\n".join(parts)
        print(f"  [calameo] Tesseract : {len(result)} chars")
        return result
    return ""


def _ocr_easyocr(images: list) -> str:
    """OCR EasyOCR avec tri des blocs par position verticale."""
    try:
        import easyocr
        import numpy as np
    except ImportError:
        return ""

    try:
        reader = easyocr.Reader(["fr", "en"], gpu=False, verbose=False)
        parts: list[str] = []
        for i, img in enumerate(images, 1):
            arr = np.array(img)
            # detail=1 → retourne (bbox, text, confidence) pour pouvoir trier par Y
            results = reader.readtext(arr, detail=1, paragraph=False)
            # Trier par position Y du coin supérieur gauche de la bbox
            results.sort(key=lambda r: r[0][0][1])
            lines = [text for (_bbox, text, _conf) in results if text.strip()]
            if lines:
                parts.append(f"— Page {i} —\n" + "\n".join(lines))
        if parts:
            result = "\n\n".join(parts)
            print(f"  [calameo] EasyOCR : {len(result)} chars")
            return result
    except Exception as e:
        print(f"  [calameo] EasyOCR erreur : {e}")
    return ""


def _dismiss_consent(page) -> None:
    """
    Ferme le bandeau de consentement CookieBot.
    On clique "Deny" (refus) — cela ferme la popup ET charge quand même le contenu.
    """
    selectors = [
        # CookieBot : Deny d'abord (le plus fiable sur Calameo)
        "#CybotCookiebotDialogBodyButtonDecline",
        # CookieBot : Allow all (si Deny absent)
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
        # Génériques
        'button:has-text("Tout accepter")',
        'button:has-text("Accept all")',
        'button:has-text("Allow all")',
        "#onetrust-accept-btn-handler",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2_000):
                btn.click()
                print(f"  [calameo] Consentement fermé ({sel[:50]})")
                return
        except Exception:
            continue


def _walk_json(obj, out: list[str], depth: int = 0) -> None:
    """Parcourt récursivement un objet JSON à la recherche de texte lisible."""
    import re as _re
    if depth > 8:
        return
    if isinstance(obj, str):
        s = obj.strip()
        # Doit contenir au moins un espace (vrai texte) et ne pas être un hash/base64/URL
        if (
            len(s) > 15
            and " " in s                          # texte lisible a des espaces
            and not s.startswith("http")
            and not s.startswith("{")
            and not _re.fullmatch(r"[A-Za-z0-9+/=\-_]{30,}", s)  # exclure base64/hashes
        ):
            out.append(s)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_json(v, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json(item, out, depth + 1)
