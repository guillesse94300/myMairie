#!/usr/bin/env python3
"""
Génère un CSV local "Pierrefonds uniquement" à partir des données DVF.

Deux sources possibles :
1. Données récentes (recommandé) : fichiers officiels DGFiP (demandes de valeurs
   foncières) par millésime — 2025 S1, 2024, 2023 — format .txt dans .zip, séparateur |.
2. Ancienne source : compilation data.gouv (CSV Oise), moins à jour.

Usage :
  python dvf_pierrefonds_csv.py              # récent : télécharge DGFiP 2025-s1 + 2024 + 2023
  python dvf_pierrefonds_csv.py --ancien    # ancien : CSV compilation Oise (si présent)
  python dvf_pierrefonds_csv.py fichier.csv # filtre un CSV local (colonnes type compilation)
"""

import sys
import zipfile
from io import StringIO, BytesIO
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Installation requise : pip install pandas")
    sys.exit(1)

# Code commune INSEE Pierrefonds (Oise) — 5 chiffres
CODE_COMMUNE_PIERREFONDS = "60491"
# Code commune 3 chiffres (format DGFiP brut)
CODE_COMMUNE_PIERREFONDS_3 = "491"
CODE_DEPARTEMENT_OISE = "60"

# URLs des fichiers DGFiP (mise à jour oct. 2025)
URLS_DGFIP = {
    "2025-s1": "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20251018-234902/valeursfoncieres-2025-s1.txt.zip",
    "2024": "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20251018-234857/valeursfoncieres-2024.txt.zip",
    "2023": "https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres/20251018-234851/valeursfoncieres-2023.txt.zip",
}

# 43 colonnes du fichier brut DGFiP (séparateur |, pas d'en-tête) — ordre notice descriptive
COLONNES_DGFIP = [
    "code_service_ch",
    "reference_document",
    "art_cgi_1",
    "art_cgi_2",
    "art_cgi_3",
    "art_cgi_4",
    "art_cgi_5",
    "numero_disposition",
    "date_mutation",
    "nature_mutation",
    "valeur_fonciere",
    "adresse_numero",
    "btq",
    "type_voie",
    "code_voie",
    "voie",
    "code_postal",
    "nom_commune",
    "code_departement",
    "code_commune",
    "prefixe_section",
    "section",
    "numero_plan",
    "numero_volume",
    "lot1_numero",
    "lot1_surface_carrez",
    "lot2_numero",
    "lot2_surface_carrez",
    "lot3_numero",
    "lot3_surface_carrez",
    "lot4_numero",
    "lot4_surface_carrez",
    "lot5_numero",
    "lot5_surface_carrez",
    "nombre_lots",
    "code_type_local",
    "type_local",
    "id_local",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "nature_culture",
    "nature_culture_speciale",
    "surface_terrain",
]


def download_url(url: str) -> bytes:
    """Télécharge une URL et retourne le contenu binaire."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mairie-Pierrefonds-DVF/1.0"})
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def extract_txt_from_zip(zip_bytes: bytes) -> str:
    """Extrait le premier fichier .txt du zip (UTF-8)."""
    with zipfile.ZipFile(BytesIO(zip_bytes), "r") as z:
        for name in z.namelist():
            if name.lower().endswith(".txt"):
                with z.open(name) as f:
                    return f.read().decode("utf-8", errors="replace")
    raise ValueError("Aucun fichier .txt dans le zip")


def charger_dgfip_millésime(url: str, lib: str) -> pd.DataFrame:
    """Télécharge un zip DGFiP, extrait le .txt, charge en DataFrame (43 colonnes, |)."""
    print(f"  Téléchargement {lib}...")
    zip_bytes = download_url(url)
    txt = extract_txt_from_zip(zip_bytes)
    print(f"  Lecture {lib} ({len(txt) // 1024} Ko texte)...")
    df = pd.read_csv(
        StringIO(txt),
        sep="|",
        header=None,
        names=COLONNES_DGFIP,
        dtype=str,
        low_memory=False,
        on_bad_lines="skip",
    )
    return df


def filtrer_pierrefonds_dgfip(df: pd.DataFrame) -> pd.DataFrame:
    """Filtre sur département 60 et commune Pierrefonds (491 ou 60491)."""
    dep = df["code_departement"].astype(str).str.strip()
    com = df["code_commune"].astype(str).str.strip()
    # DGFiP : code_commune souvent 3 chiffres (491), parfois 5 (60491)
    ok_dep = dep == CODE_DEPARTEMENT_OISE
    ok_com = (com == CODE_COMMUNE_PIERREFONDS_3) | (com == CODE_COMMUNE_PIERREFONDS)
    return df.loc[ok_dep & ok_com].copy()


def generer_recent(project_root: Path, out_csv: Path) -> int:
    """Télécharge DGFiP 2025-s1, 2024, 2023 ; filtre Pierrefonds ; enregistre CSV."""
    frames = []
    for lib, url in URLS_DGFIP.items():
        try:
            df = charger_dgfip_millésime(url, lib)
            df = filtrer_pierrefonds_dgfip(df)
            if len(df) > 0:
                df["millesime"] = lib
                frames.append(df)
                print(f"  -> {len(df)} lignes Pierrefonds pour {lib}")
        except Exception as e:
            print(f"  Erreur {lib}: {e}")
    if not frames:
        print("Aucune donnée Pierrefonds trouvée dans les fichiers DGFiP.")
        return 1
    out = pd.concat(frames, ignore_index=True)
    # Tri par date
    if "date_mutation" in out.columns:
        out["date_mutation"] = pd.to_datetime(out["date_mutation"], dayfirst=True, errors="coerce")
        out = out.sort_values("date_mutation", ascending=False)
    out.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"CSV genere : {out_csv} ({len(out)} lignes)")
    return 0


def generer_ancien(project_root: Path, out_csv: Path) -> int:
    """Utilise le CSV compilation Oise (data/dvf-60.csv) si présent."""
    cache = project_root / "data" / "dvf-60.csv"
    url_compilation = "https://static.data.gouv.fr/resources/compilation-des-donnees-de-valeurs-foncieres-dvf-par-departement/20230505-170233/dvf-60.csv"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            import urllib.request
            print(f"Téléchargement compilation Oise : {url_compilation}")
            urllib.request.urlretrieve(url_compilation, cache)
        except Exception as e:
            print(f"Erreur : {e}. Indiquez un fichier local ou utilisez le mode récent (sans --ancien).")
            return 1
    print(f"Lecture {cache}...")
    df = pd.read_csv(cache, dtype={"code_commune": str, "code_departement": str}, low_memory=False)
    df = df[df["code_commune"].astype(str).str.strip() == CODE_COMMUNE_PIERREFONDS].copy()
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"CSV genere : {out_csv} ({len(df)} lignes)")
    return 0


def main():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    out_csv = project_root / "dvf_pierrefonds.csv"

    if len(sys.argv) > 1 and sys.argv[1] == "--ancien":
        return generer_ancien(project_root, out_csv)

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        # Fichier CSV local (format type compilation)
        source = Path(sys.argv[1])
        if not source.exists():
            print(f"Fichier introuvable : {source}")
            return 1
        print(f"Lecture {source}...")
        df = pd.read_csv(source, dtype={"code_commune": str, "code_departement": str}, low_memory=False)
        df = df[df["code_commune"].astype(str).str.strip() == CODE_COMMUNE_PIERREFONDS].copy()
        df.to_csv(out_csv, index=False, encoding="utf-8")
        print(f"CSV genere : {out_csv} ({len(df)} lignes)")
        return 0

    # Par défaut : données récentes DGFiP
    print("Source : fichiers officiels DGFiP (2025 S1, 2024, 2023)")
    return generer_recent(project_root, out_csv)


if __name__ == "__main__":
    sys.exit(main())
