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


# ── Extraction des horaires ────────────────────────────────────────────────────
def parse_horaires(text):
    """Extrait heure début, heure fin et durée en minutes."""
    # Heure début : première occurrence dans les 1000 premiers caractères
    m_start = re.search(r'[àa]\s*(\d{1,2})[hH](\d{0,2})', text[:1000])
    # Heure fin : "levée à HHhMM" n'importe où dans le texte
    m_end = re.search(r'lev[eé]e?\s+[àa]\s+(\d{1,2})[hH](\d{0,2})', text, re.IGNORECASE)

    heure_debut = heure_fin = duree_minutes = None

    if m_start:
        h  = int(m_start.group(1))
        mn = int(m_start.group(2)) if m_start.group(2) else 0
        heure_debut = f"{h:02d}:{mn:02d}"
        debut_min   = h * 60 + mn

    if m_end:
        h  = int(m_end.group(1))
        mn = int(m_end.group(2)) if m_end.group(2) else 0
        heure_fin = f"{h:02d}:{mn:02d}"
        fin_min   = h * 60 + mn
        if m_start:
            diff = fin_min - debut_min
            if 0 < diff < 480:   # max 8 h de séance
                duree_minutes = diff

    return heure_debut, heure_fin, duree_minutes


# ── Extraction de la date ──────────────────────────────────────────────────────
def parse_date(text):
    # Nouveau format : "Conseil Municipal du 27/01/2025"
    m = re.search(r'Conseil Municipal du (\d{1,2})/(\d{2})/(\d{4})', text, re.IGNORECASE)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    # Ancien format : "Conseil Municipal du 01 mars 2022"
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

    # Unanimité (ancien et nouveau format)
    if re.search(r'unanimit|unanimement|d[eé]lib[eé]r[eé].*unanim|unanim.*d[eé]lib[eé]r[eé]', low):
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

    # ── Nouveau format (2024+) : "D2024-44 - Objet : ..." ────────────────────
    new_blocks = re.split(r'\n(?=D\d{4}-\d{1,4}\s*[-–])', text)
    if len(new_blocks) > 1:
        for i, block in enumerate(new_blocks[1:], 1):
            m_title = re.match(r'^(D\d{4}-\d{1,4})\s*[-–]\s*(?:Objet\s*:\s*)?(.+?)(?:\n|$)', block)
            if not m_title:
                continue
            num_str = m_title.group(1)
            titre   = m_title.group(2).strip()[:200]
            vote    = parse_vote(block)
            theme   = classify_theme(titre + " " + block[:600])
            delibs.append({"num": i, "num_str": num_str, "titre": titre,
                           "vote": vote, "theme": theme})
        return delibs

    # ── Ancien format : "1. Titre en majuscule\n" ─────────────────────────────
    old_blocks = re.split(r'\n(?=\d{1,2}\.\s+[A-ZÀÂÉÈÊËÎÏÔÙÛÜÇ«])', text)
    for block in old_blocks[1:]:
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
    heure_debut, heure_fin, duree_minutes = parse_horaires(text)

    return {
        "fichier":          pdf_path.name,
        "date":             date.strftime("%Y-%m-%d") if date else None,
        "annee":            date.year if date else None,
        "heure_debut":      heure_debut,
        "heure_fin":        heure_fin,
        "duree_minutes":    duree_minutes,
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
            duree = f"{data['duree_minutes']}min" if data['duree_minutes'] else "?min"
            print(f"-> {date}  {nb} deliberations  {data['nb_presences']} presents  {duree}")
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
