"""
Copie les fichiers .md (knowledge_sites + racine) vers static/
pour qu'ils soient servis et listés dans Sources et Documents.
À lancer avant un déploiement si les .md ont changé.
"""
import shutil
from pathlib import Path

APP_DIR = Path(__file__).parent
STATIC = APP_DIR / "static"
KNOWLEDGE = APP_DIR / "knowledge_sites"

def main():
    STATIC.mkdir(exist_ok=True)
    n = 0
    # .md à la racine (sources, pas README)
    for p in APP_DIR.glob("*.md"):
        if p.name.upper() == "README.MD":
            continue
        dest = STATIC / p.name
        shutil.copy2(p, dest)
        print(f"  {p} -> {dest}")
        n += 1
    # knowledge_sites/**/*.md
    if KNOWLEDGE.exists():
        for p in KNOWLEDGE.rglob("*.md"):
            rel = p.relative_to(KNOWLEDGE)
            dest = STATIC / "knowledge_sites" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            print(f"  {p} -> {dest}")
            n += 1
    print(f"\nCopié {n} fichier(s) .md dans {STATIC}")

if __name__ == "__main__":
    main()
