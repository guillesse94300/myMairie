"""
stats_extract.py — Extraction des statistiques de vote des PV du Conseil Municipal
Génère vector_db/stats.json
Usage : python stats_extract.py
"""

import re
import json
import pdfplumber
from pathlib import Path
from datetime import datetime

PDF_DIR = Path(__file__).parent / "static"
DB_DIR  = Path(__file__).parent / "vector_db"

MOIS_FR = {
    'janvier': 1, 'fevrier': 2, 'février': 2, 'mars': 3, 'avril': 4,
    'mai': 5, 'juin': 6, 'juillet': 7, 'aout': 8, 'août': 8,
    'septembre': 9, 'octobre': 10, 'novembre': 11, 'decembre': 12, 'décembre': 12,
}

THEME_PATTERNS = {
    "Convention / Contrat": r'convention|contrat|accord|partenariat|prestataire|sign',
    "Budget / Finances":    r'budget|subvention|investissement|d.pense|recette|dotation|emprunt',
    "Emploi / RH":          r'emploi|recrutement|agent|personnel|r.mun.ration|poste|vacataire',
    "Tarifs / Redevances":  r'tarif|redevance|bar.me|taux|cotisation',
    "École / Scolaire":     r'scolaire|.cole|enseignement|p.riscolaire|classe|cantine|ATSEM',
    "Travaux / Voirie":     r'travaux|voirie|chauss.e|route|chemin|r.fection|r.novation',
    "Énergie / Éclairage":  r'.nergie|.lectricit.|SIED|.clairage|photovolta',
    "Forêt / Bois":         r'for.t|boisement|Haucourt|Vertefeuille|sylviculture',
    "Urbanisme / Permis":   r'permis.*construire|PLU|urbanisme|zonage|lotissement',
    "Enfance / Jeunesse":   r'enfants|jeunesse|loisirs|accueil|centre.*loisir|ALSH',
}


# ── Extraction de la date ──────────────────────────────────────────────────────
def parse_date(text):
    # "Conseil Municipal du 01 mars 2022"
    m = re.search(
        r'Conseil Municipal du (\d{1,2})\s+(\w+)\s+(\d{4})',
        text, re.IGNORECASE
    )
    if m:
        day = int(m.group(1))
        month = MOIS_FR.get(m.group(2).lower().replace('é','e').replace('û','u').replace('è','e'))
        year = int(m.group(3))
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                pass
    # Fallback : extraire l'année depuis le nom de fichier n'est pas possible ici
    return None


# ── Extraction des membres ─────────────────────────────────────────────────────
def parse_membres(text):
    presences, absences, pouvoirs = [], [], []

    # Présents
    m = re.search(
        r'Pr[eé]sents?\s*:(.*?)(?:Pouvoirs?|Absents?|Secr[eé]taire|_{4,})',
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        bloc = m.group(1)
        noms = re.findall(r'\b([A-ZÉÈÊÀÂÙÛÎÔÄ][A-ZÉÈÊÀÂÙÛÎÔÄ\-]{2,})\b', bloc)
        # Filtrer les faux positifs (mots courants en majuscules)
        exclus = {'PIERREFONDS', 'ARRIVÉ', 'ARRIVEE', 'CONSEIL', 'MUNICIPAL'}
        presences = [n for n in dict.fromkeys(noms) if n not in exclus]

    # Absents
    m = re.search(
        r'Absents?\s*:(.*?)(?:Secr[eé]taire|_{4,}|\Z)',
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        bloc = m.group(1)[:400]
        noms = re.findall(r'\b([A-ZÉÈÊÀÂÙÛÎÔÄ][A-ZÉÈÊÀÂÙÛÎÔÄ\-]{2,})\b', bloc)
        absences = list(dict.fromkeys(noms))

    # Pouvoirs : "Madame X à Madame Y"
    m = re.search(
        r'Pouvoirs?\s*:(.*?)(?:Absents?|Secr[eé]taire|_{4,})',
        text, re.IGNORECASE | re.DOTALL
    )
    if m:
        bloc = m.group(1)
        pairs = re.findall(
            r'(?:Mme?\.?\s+|Madame\s+|Monsieur\s+|M\.\s+)'
            r'(?:[A-Zéèêàâùûîôä\-]+\s+)?'
            r'([A-ZÉÈÊÀÂÙÛÎÔÄ][A-ZÉÈÊÀÂÙÛÎÔÄ\-]{2,})'
            r'\s+[àa]\s+'
            r'(?:Mme?\.?\s+|Madame\s+|Monsieur\s+|M\.\s+)'
            r'(?:[A-Zéèêàâùûîôä\-]+\s+)?'
            r'([A-ZÉÈÊÀÂÙÛÎÔÄ][A-ZÉÈÊÀÂÙÛÎÔÄ\-]{2,})',
            bloc
        )
        pouvoirs = [{"de": a, "a": b} for a, b in pairs]

    return presences, absences, pouvoirs


# ── Extraction du vote ─────────────────────────────────────────────────────────
def parse_vote(block):
    low = block.lower()

    # Unanimité
    if re.search(r'unanimit|unanimement', low):
        return {"type": "unanimité", "pour": None, "contre": 0, "abstentions": 0,
                "noms_abstentions": [], "noms_contre": []}

    # Décompte explicite
    m = re.search(
        r'[Pp]our\s*:\s*(\d+)'
        r'(?:.*?[Cc]ontre\s*:\s*(\d+)(?:\s*\(([^)]*)\))?)?'
        r'(?:.*?[Aa]bstentions?\s*:\s*(\d+)(?:\s*\(([^)]*)\))?)?',
        block, re.DOTALL
    )
    if m:
        pour  = int(m.group(1))
        contre = int(m.group(2)) if m.group(2) else 0
        abst   = int(m.group(4)) if m.group(4) else 0
        noms_contre = re.findall(
            r'\b([A-ZÉÈÊÀÂÙÛÎÔÄ][A-ZÉÈÊÀÂÙÛÎÔÄ\-]{2,})\b', m.group(3) or ''
        )
        noms_abst = re.findall(
            r'\b([A-ZÉÈÊÀÂÙÛÎÔÄ][A-ZÉÈÊÀÂÙÛÎÔÄ\-]{2,})\b', m.group(5) or ''
        )
        return {"type": "vote", "pour": pour, "contre": contre, "abstentions": abst,
                "noms_abstentions": noms_abst, "noms_contre": noms_contre}

    # Adopté sans décompte -> présumé unanimité
    if re.search(r'adopt[eé]|approuv', low):
        return {"type": "unanimité", "pour": None, "contre": 0, "abstentions": 0,
                "noms_abstentions": [], "noms_contre": []}

    return {"type": "inconnu", "pour": None, "contre": None, "abstentions": None,
            "noms_abstentions": [], "noms_contre": []}


# ── Classification thématique ──────────────────────────────────────────────────
def classify_theme(text):
    best, best_n = "Autre", 0
    for theme, pat in THEME_PATTERNS.items():
        n = len(re.findall(pat, text, re.IGNORECASE))
        if n > best_n:
            best_n, best = n, theme
    return best


# ── Extraction des délibérations ───────────────────────────────────────────────
def parse_deliberations(text):
    delibs = []
    # Découper sur les titres numérotés "1. Titre\n"
    blocks = re.split(r'\n(?=\d{1,2}\.\s+[A-ZÀÂÉÈÊËÎÏÔÙÛÜÇ«])', text)

    for block in blocks[1:]:
        m_title = re.match(r'^(\d{1,2})\.\s+(.+?)(?:\n|$)', block)
        if not m_title:
            continue
        num   = int(m_title.group(1))
        titre = m_title.group(2).strip()[:200]
        vote  = parse_vote(block)
        theme = classify_theme(titre + " " + block[:600])
        delibs.append({"num": num, "titre": titre, "vote": vote, "theme": theme})

    return delibs


# ── Extraction d'un PDF ────────────────────────────────────────────────────────
def extract_pdf(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    date = parse_date(text)
    presences, absences, pouvoirs = parse_membres(text)
    delibs = parse_deliberations(text)

    return {
        "fichier":          pdf_path.name,
        "date":             date.strftime("%Y-%m-%d") if date else None,
        "annee":            date.year if date else None,
        "presences":        presences,
        "nb_presences":     len(presences),
        "absences":         absences,
        "nb_absences":      len(absences),
        "pouvoirs":         pouvoirs,
        "nb_deliberations": len(delibs),
        "deliberations":    delibs,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    DB_DIR.mkdir(exist_ok=True)
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    print(f"Extraction de {len(pdfs)} PDFs…\n")

    seances, errors = [], []

    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i:2d}/{len(pdfs)}] {pdf.name}", end=" ")
        try:
            data = extract_pdf(pdf)
            seances.append(data)
            nb = data["nb_deliberations"]
            date = data["date"] or "?"
            print(f"-> {date}  {nb} délibérations  {data['nb_presences']} présents")
        except Exception as e:
            print(f"-> ERREUR : {e}")
            errors.append({"fichier": pdf.name, "erreur": str(e)})

    # Trier par date
    seances.sort(key=lambda s: s.get("date") or "0000-00-00")

    out = {
        "generated_at":  datetime.now().isoformat(),
        "nb_pdfs":       len(pdfs),
        "nb_seances":    len(seances),
        "seances":       seances,
        "errors":        errors,
    }

    out_path = DB_DIR / "stats.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nOK {len(seances)} séances -> {out_path}")
    if errors:
        print(f"WARN  {len(errors)} erreurs")


if __name__ == "__main__":
    main()
