# -*- coding: utf-8 -*-
"""Recherche de termes dans tous les PDF du dossier."""
import os
from pathlib import Path
from pypdf import PdfReader

DOSSIER = Path(__file__).resolve().parent
TERMES = [
    "Bois d'Haucourt",
    "Sente Brunehaut",
    "Vertefeuille",
    "VTT",
    "Chasse",
]

def normalise(s):
    return s.replace("\r", " ").replace("\n", " ").replace("  ", " ")

def main():
    resultats = {t: [] for t in TERMES}
    pdfs = sorted(p for p in DOSSIER.glob("*.pdf") if p.is_file())

    for path in pdfs:
        try:
            reader = PdfReader(str(path))
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            text_norm = normalise(text)
            name = path.name
            for terme in TERMES:
                if terme.lower() in text_norm.lower():
                    resultats[terme].append(name)
        except Exception as e:
            print(f"Erreur {path.name}: {e}")

    print("=" * 60)
    print("RECHERCHE DANS LES DOCUMENTS (PDF)")
    print("=" * 60)
    for terme in TERMES:
        fichiers = resultats[terme]
        print(f"\n--- {terme} ---")
        if fichiers:
            for f in fichiers:
                print(f"  • {f}")
            print(f"  Total: {len(fichiers)} fichier(s)")
        else:
            print("  Aucune mention trouvée.")

if __name__ == "__main__":
    main()
