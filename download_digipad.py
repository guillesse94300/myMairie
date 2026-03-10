"""
Télécharge tous les PDFs du Digipad Ressources Pédagogiques du Château de Pierrefonds.
Source : https://digipad.app/p/495670/90c1b7d40b779
Stockage S3 : https://digipad.s3.sbg.io.cloud.ovh.net/495670/
"""

import os
import requests
from pathlib import Path

BASE_URL = "https://digipad.s3.sbg.io.cloud.ovh.net/495670/"
OUTPUT_DIR = Path(__file__).parent / "static" / "digipad_chateau"

PDF_FILES = [
    "fiche-pratique-scolaires_pierrefonds_zztq61s03wp.pdf",
    "mini-fiche-visite-27112021_38lqxrmdk13.pdf",
    "tutoriel-pass-culture-pierrefonds_pwwoqzwhzl.pdf",
    "bts---cg-les-animaux---la-fontaine---pierrefonds_damfon6mo74.pdf",
    "vld-a-pierrefonds_6ln4jpoqexx.pdf",
    "patrimoine_h2gsp_1y1u3wzny0k.pdf",
    "legende_arthurienne_mi7e0s470a.pdf",
    "sciences-et-patrimoine_crej2x0zt9m.pdf",
    "livret-pedago-enseignants_cjndzx9d4rm.pdf",
    "questionnaire-collage-visite-libre-2025_glufv1wco5v.pdf",
    "fiche-focus_lion-aila_1t1e93v356w.pdf",
    "cheminae-des-preuses_salle-des-preuses_vld_3u3faevx11.pdf",
    "fichefocus_graffiti_z7nrmg4afdp.pdf",
    "faaade-intarieure_cour-dhonneur_vld_0fg3yu3u4q7e.pdf",
    "armoiries_circuit-de-visite_vld_8pobtsr0s7s.pdf",
    "charpente-matallique_98n8isg3xvu.pdf",
    "fortifications-dafensives_faaade-sud_vld_wv3qmizupb.pdf",
    "art-nouveau_fiche-focus_gfhwe8iemip.pdf",
    "pem2025_d0hc6k7sw3u.pdf",
]

def download_all(output_dir=None):
    out = Path(output_dir) if output_dir else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    success = 0
    errors = []

    for filename in PDF_FILES:
        url = BASE_URL + filename
        dest = out / filename

        if dest.exists():
            print(f"  [SKIP] {filename} (déjà téléchargé)")
            success += 1
            continue

        print(f"  [DL]   {filename} ...", end=" ", flush=True)
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            dest.write_bytes(r.content)
            size_kb = len(r.content) / 1024
            print(f"OK ({size_kb:.0f} Ko)")
            success += 1
        except Exception as e:
            print(f"ERREUR: {e}")
            errors.append((filename, str(e)))

    print(f"\n{'='*50}")
    print(f"Téléchargés : {success}/{len(PDF_FILES)}")
    if errors:
        print(f"Erreurs : {len(errors)}")
        for f, e in errors:
            print(f"  - {f}: {e}")
    print(f"Dossier : {out}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Telecharge les PDFs Digipad Chateau de Pierrefonds")
    p.add_argument("-o", "--output", default="source/pdf",
                   help="Dossier de sortie (defaut : source/pdf)")
    args = p.parse_args()
    download_all(args.output)
