"""
app.py — Interface Streamlit de recherche dans les comptes rendus
Usage  : streamlit run app.py
"""

import re
import sqlite3
import warnings

# Supprimer les warnings non bloquants (pin_memory, HF Hub)
warnings.filterwarnings("ignore", message=".*pin_memory.*", category=UserWarning)
warnings.filterwarnings("ignore", message=".*HF_TOKEN.*", category=UserWarning)
import json
import pickle
import subprocess
import csv
import io
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter, defaultdict
from sentence_transformers import SentenceTransformer
from pathlib import Path

try:
    from groq import Groq as _Groq
    _GROQ_OK = True
except ImportError:
    _GROQ_OK = False

try:
    from rank_bm25 import BM25Okapi as _BM25Okapi
    _BM25_OK = True
except ImportError:
    _BM25_OK = False

try:
    from streamlit_javascript import st_javascript
    _ST_JS_OK = True
except ImportError:
    _ST_JS_OK = False

# ── Configuration ──────────────────────────────────────────────────────────────
APP_DIR  = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
PDF_DIR  = APP_DIR / "static"          # PDFs servis par Streamlit static serving
DB_DIR   = APP_DIR / "vector_db"
SEARCHES_DB = DATA_DIR / "searches.db"  # SQLite : IP, timestamp, requête
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# URL de base pour les PDFs (fonctionne local ET sur Streamlit Cloud)
PDF_BASE_URL = "https://raw.githubusercontent.com/guillesse94300/myMairie/main/static"


def _safe_pdf_url(rel_path: str) -> str:
    """
    Retourne une URL relative sûre pour un PDF (pas de .. ni de scheme malveillant).
    En cas de valeur suspecte, retourne '#' pour désactiver le lien.
    """
    if not rel_path or not isinstance(rel_path, str):
        return "#"
    # Supprimer tout scheme (javascript:, data:, etc.)
    if ":" in rel_path and rel_path.split(":")[0].strip().lower() in ("javascript", "data", "vbscript"):
        return "#"
    # Pas de path traversal
    if ".." in rel_path or rel_path.startswith("/"):
        return "#"
    # Nettoyer les backslashes
    clean = rel_path.replace("\\", "/").strip()
    if not clean:
        return "#"
    return f"{PDF_BASE_URL}/{clean}"


def _safe_source_url(url: str) -> str | None:
    """Accepte uniquement http/https. Sinon retourne None."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip().lower()
    if u.startswith("https://") or u.startswith("http://"):
        return url.strip()
    return None


# ── Rate limiting par IP (recherche + agent) : 5 recherches / jour ──────────────
RATE_LIMIT_MAX = 5
RATE_LIMIT_WHITELIST = {"86.208.120.20", "90.22.160.8", "37.64.40.130"}
# Bonus de crédits par IP (ex. 20 = 5+20 = 25 recherches/jour)
RATE_LIMIT_CREDITS_BONUS = {"80.214.57.209": 20}
QUOTA_EPUISE_MSG = "Quota de recherche épuisé, attendez minuit !"


def _init_searches_db() -> None:
    """Crée le dossier data et la table SQLite si besoin."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(SEARCHES_DB) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS searches "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, timestamp REAL, query TEXT)"
            )
    except Exception:
        pass


def log_search(ip: str | None, query: str) -> None:
    """Enregistre une recherche (IP, timestamp, requête) en SQLite."""
    if not query or not query.strip():
        return
    try:
        _init_searches_db()
        with sqlite3.connect(SEARCHES_DB) as conn:
            conn.execute(
                "INSERT INTO searches (ip, timestamp, query) VALUES (?, ?, ?)",
                (ip or "", datetime.now().timestamp(), (query or "").strip()[:2000]),
            )
    except Exception:
        pass


def get_client_ip() -> str | None:
    """IP du client (X-Forwarded-For, X-Real-Ip, CF-Connecting-IP, sinon st.context)."""
    try:
        ctx = st.context
        if hasattr(ctx, "headers") and ctx.headers:
            xff = ctx.headers.get("x-forwarded-for") or ctx.headers.get("X-Forwarded-For")
            if xff:
                return xff.split(",")[0].strip()
            xri = ctx.headers.get("x-real-ip") or ctx.headers.get("X-Real-Ip")
            if xri:
                return xri.strip()
            cf = ctx.headers.get("cf-connecting-ip") or ctx.headers.get("CF-Connecting-IP")
            if cf:
                return cf.strip()
        if hasattr(ctx, "ip_address") and ctx.ip_address:
            return str(ctx.ip_address)
    except Exception:
        pass
    return None


def get_client_ip_for_log() -> str | None:
    """IP pour log_search : priorité à l'IP publique côté client (même source que le bandeau), sinon get_client_ip()."""
    # IP publique récupérée côté client via api.ipify.org (comme le bandeau)
    ip = st.session_state.get("client_public_ip")
    if ip:
        return ip
    return get_client_ip()


def _get_searches_today_count_for_ip(ip: str) -> int:
    """Nombre de recherches aujourd'hui pour cette IP (base SQLite)."""
    if not ip:
        return 0
    try:
        _init_searches_db()
        with sqlite3.connect(SEARCHES_DB) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM searches WHERE ip = ? AND date(timestamp, 'unixepoch', 'localtime') = date('now', 'localtime')",
                (ip,),
            )
            return cur.fetchone()[0] or 0
    except Exception:
        return 0


def _get_rate_limit_max_for_ip(ip: str) -> int:
    """Limite max pour cette IP (base + bonus crédits)."""
    return RATE_LIMIT_MAX + RATE_LIMIT_CREDITS_BONUS.get(ip, 0)


def rate_limit_check_and_consume() -> tuple[bool, int | None]:
    """
    Vérifie la limite (5 recherches / jour par IP). La consommation a lieu lors de log_search().
    Retourne (autorisé, restant). restant est None si IP whitelistée ou inconnue.
    """
    ip = get_client_ip_for_log()
    if not ip:
        return (True, None)
    if ip in RATE_LIMIT_WHITELIST:
        return (True, None)
    count_today = _get_searches_today_count_for_ip(ip)
    max_allowed = _get_rate_limit_max_for_ip(ip)
    if count_today >= max_allowed:
        return (False, 0)
    return (True, max_allowed - count_today - 1)


def rate_limit_get_remaining() -> int | None:
    """Nombre de recherches restantes aujourd'hui (sans consommer). None si whitelist ou IP inconnue."""
    ip = get_client_ip_for_log()
    if not ip or ip in RATE_LIMIT_WHITELIST:
        return None
    count_today = _get_searches_today_count_for_ip(ip)
    max_allowed = _get_rate_limit_max_for_ip(ip)
    return max(0, max_allowed - count_today)


def rate_limit_get_max_for_display() -> int:
    """Max affiché pour l'IP courante (pour le bandeau X/max)."""
    ip = get_client_ip_for_log() or get_client_ip()
    return _get_rate_limit_max_for_ip(ip) if ip else RATE_LIMIT_MAX


def get_searches_today_count() -> int:
    """Nombre total de recherches depuis minuit (ce matin), lu depuis la base SQLite."""
    try:
        _init_searches_db()
        with sqlite3.connect(SEARCHES_DB) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM searches WHERE date(timestamp, 'unixepoch', 'localtime') = date('now', 'localtime')"
            )
            return cur.fetchone()[0] or 0
    except Exception:
        return 0


SUGGESTIONS = [
    "Bois D'Haucourt",
    "Vertefeuille",
    "permis de construire",
    "voirie",
    "budget",
    "cantine",
    "château",
    "SE60",
]

THEMES = {
    "📜 Convention / Contrat":  "convention contrat accord partenariat prestataire signature",
    "💶 Budget / Finances":     "budget subvention investissement dépenses recettes dotation emprunt",
    "👷 Emploi / RH":           "emploi recrutement agent personnel rémunération poste vacataire",
    "💰 Tarifs / Redevances":   "tarif redevance barème taux prix cotisation",
    "🏫 École / Scolaire":      "école scolaire enseignement élèves périscolaire cantine ATSEM classe Louis Lesueur",
    "🚧 Travaux / Voirie":      "travaux voirie chaussée route réfection rénovation chemin Carretero",
    "⚡ Énergie / Éclairage":   "énergie électricité éclairage SIED SE60 photovoltaïque compteur",
    "🌲 Forêt / Bois":          "forêt boisement Bois D'Haucourt Vertefeuille sylviculture coupe",
    "🏗️ Urbanisme / Permis":    "permis de construire PLU urbanisme zonage lotissement bâtiment",
    "🧒 Enfance / Jeunesse":    "enfants jeunesse loisirs accueil centre de loisirs ALSH périscolaire",
    "🤝 Intercommunalité":      "CCLoise communauté communes SMOA SIVOC SMIOCCE syndicat intercommunal Oise Compiègne",
    "🏰 Château / Tourisme":    "château Viollet-le-Duc tourisme office patrimoine restauration",
    "🎭 Culture / Associations": "association culturelle musique danse bibliothèque Foyer Napoléon SIVOC",
}

_MOIS_FR = {
    'janvier': 1, 'fevrier': 2, 'mars': 3, 'avril': 4,
    'mai': 5, 'juin': 6, 'juillet': 7, 'aout': 8,
    'septembre': 9, 'octobre': 10, 'novembre': 11, 'decembre': 12,
}

def _pdf_date_key(p: Path) -> datetime:
    """Retourne une clé datetime extraite du nom de fichier pour le tri."""
    name = p.stem
    # Format YYYYMMDD-... (ex: 20240613-PV-AFFICHAGE-1)
    m = re.match(r'^(\d{4})(\d{2})(\d{2})', name)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # Format ...-DD-MM-YYYY (ex: compte-rendu-02-02-2016)
    m = re.search(r'(\d{1,2})-(\d{2})-(\d{4})$', name)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    # Format ...-DD-MOIS-YYYY (ex: CM-01-MARS-2022, CM-du-10-avril-2024)
    m = re.search(r'[^\d](\d{1,2})-([a-zA-Zéûèà]+)-(\d{4})', name, re.IGNORECASE)
    if m:
        mon = m.group(2).lower()
        mon = mon.replace('é', 'e').replace('è', 'e').replace('û', 'u').replace('à', 'a')
        month_num = _MOIS_FR.get(mon)
        if month_num:
            try:
                return datetime(int(m.group(3)), month_num, int(m.group(1)))
            except ValueError:
                pass
    # Juste une année (ex: REPERTOIRE-CHRONOLOGIQUE-2024-...)
    m = re.search(r'\b(\d{4})\b', name)
    if m:
        year = int(m.group(1))
        if 1900 <= year <= 2100:
            return datetime(year, 1, 1)
    return datetime.min


# ── Liens noms propres dans les réponses ────────────────────────────────────────
import urllib.parse

NOMS_PROPRES_LIENS: dict[str, str] = {
    "Eugène Viollet-le-Duc":   "Qui était Eugène Viollet-le-Duc ?",
    "Viollet-le-Duc":          "Qui était Viollet-le-Duc ?",
    "Lucjan Wyganowski":       "Qui était Lucjan Wyganowski ?",
    "Wyganowski":              "Qui était Wyganowski ?",
    "Amédée Scelles":          "Qui était Amédée Scelles ?",
    "Pierre Lecot":            "Qui était Pierre Lecot ?",
    "Paul Devilliers":         "Qui était Paul Devilliers ?",
    "Napoléon III":            "Qui était Napoléon III ?",
    "Napoléon Ier":            "Qui était Napoléon Ier ?",
    "Louis d'Orléans":         "Qui était Louis d'Orléans, duc d'Orléans ?",
    "Richelieu":               "Qui était Richelieu ?",
    "Florence Demouy":         "Qui est Florence Demouy, maire de Pierrefonds ?",
    "Jean-Jacques Carretero":  "Qui est Jean-Jacques Carretero ?",
    "Emmanuelle Lemaitre":     "Qui est Emmanuelle Lemaitre ?",
    "Romain Ribeiro":          "Qui est Romain Ribeiro ?",
}

def _lier_noms_propres(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Met en gras les noms propres connus et retourne la liste trouvée.

    Retourne (texte_modifié, [(nom_affiché, question), ...]).
    Les noms sont mis en **gras** dans le texte (pas de lien <a> car Streamlit
    force target="_blank" et ouvre un nouvel onglet).
    Les boutons Streamlit natifs « En savoir plus » permettent de relancer
    la recherche dans la même page.
    """
    found: dict[str, str] = {}          # nom → question (dédupliqué)
    noms_tries = sorted(NOMS_PROPRES_LIENS.items(), key=lambda x: -len(x[0]))
    for nom, question in noms_tries:
        bold = f"**{nom}**"
        # Vérifier si le nom est dans le texte (hors balises HTML et hors gras existant)
        if nom not in text:
            continue
        # Déjà en gras → juste noter le nom
        if bold in text:
            found[nom] = question
            continue
        # Mettre en gras (simple remplacement, en évitant l'intérieur des balises HTML)
        parts = re.split(r'(<[^>]+>)', text)
        result = []
        for part in parts:
            if part.startswith('<'):
                result.append(part)
            else:
                if nom in part:
                    part = part.replace(nom, bold)
                    found[nom] = question
                result.append(part)
        text = ''.join(result)
    return text, list(found.items())


# ── Mode admin ─────────────────────────────────────────────────────────────────
def is_admin() -> bool:
    token = st.query_params.get("admin", "")
    if not token:
        return False
    try:
        secret = st.secrets.get("ADMIN_TOKEN", "")
    except Exception:
        secret = ""
    return bool(secret and token == secret)


# ── Informations Git ───────────────────────────────────────────────────────────
DEPLOY_DATE_FILE = APP_DIR / "deploy_date.txt"

@st.cache_data(show_spinner=False)
def get_git_info():
    cwd = str(APP_DIR)
    commit_date = "—"
    # Priorité : fichier mis à jour par deploy.bat (format "YYYY-MM-DD HH:MM")
    if DEPLOY_DATE_FILE.exists():
        try:
            commit_date = DEPLOY_DATE_FILE.read_text(encoding="utf-8").strip()[:16]
        except Exception:
            pass
    if commit_date == "—":
        try:
            commit_date = subprocess.check_output(
                ["git", "log", "-1", "--format=%ci"],
                cwd=cwd, stderr=subprocess.DEVNULL
            ).decode().strip()[:16]   # "YYYY-MM-DD HH:MM"
            commit_date = commit_date.replace("T", " ")
        except Exception:
            pass
    try:
        version = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=cwd, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        version = "—"
    return commit_date, version


# ── Chargement des ressources (mis en cache) ───────────────────────────────────
@st.cache_resource(show_spinner="Chargement du modele d'embeddings...")
def load_model():
    return SentenceTransformer(MODEL_NAME)


def _tokenize(text: str) -> list:
    """Tokenisation simple pour BM25 : minuscules, split sur non-alphanumérique."""
    return re.split(r"[^\w]+", text.lower())


@st.cache_resource(show_spinner="Chargement de la base vectorielle...")
def load_db():
    embeddings = np.load(DB_DIR / "embeddings.npy")
    with open(DB_DIR / "documents.pkl", "rb") as f:
        documents = pickle.load(f)
    with open(DB_DIR / "metadata.pkl", "rb") as f:
        metadata = pickle.load(f)
    # Construction de l'index BM25 (lexical) en complément des embeddings sémantiques
    bm25 = None
    if _BM25_OK:
        tokenized = [_tokenize(doc) for doc in documents]
        bm25 = _BM25Okapi(tokenized)
    return embeddings, documents, metadata, bm25


# ── Recherche hybride sémantique + BM25 ───────────────────────────────────────
# Pondération : α × sémantique + (1-α) × BM25 normalisé
_BM25_ALPHA = 0.6   # part sémantique ; 1-α = 0.4 pour BM25 lexical

def search(query: str, embeddings, documents, metadata,
           n: int = 15, year_filter: list = None, exact: bool = False,
           bm25=None):
    model = load_model()
    q_emb = model.encode([query], show_progress_bar=False)[0].astype(np.float32)
    q_emb = q_emb / max(np.linalg.norm(q_emb), 1e-9)

    sem_scores = embeddings @ q_emb  # cosine similarity ∈ [-1, 1]

    # Score BM25 : normalisé dans [0, 1] puis combiné avec le score sémantique
    if bm25 is not None:
        raw_bm25 = np.array(bm25.get_scores(_tokenize(query)), dtype=np.float32)
        bm25_max = raw_bm25.max()
        bm25_norm = raw_bm25 / bm25_max if bm25_max > 0 else raw_bm25
        scores = _BM25_ALPHA * sem_scores + (1 - _BM25_ALPHA) * bm25_norm
    else:
        scores = sem_scores

    # Filtre par année
    if year_filter:
        year_set = {str(y) for y in year_filter}
        mask = np.array([m["year"] in year_set for m in metadata], dtype=bool)
        scores = np.where(mask, scores, -1.0)

    # Filtre exact : le chunk doit contenir au moins un mot de la requête
    if exact:
        terms = [t for t in re.split(r"\s+", query) if len(t) > 2]
        pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
        mask_exact = np.array([bool(pattern.search(doc)) for doc in documents], dtype=bool)
        scores = np.where(mask_exact, scores, -1.0)

    top_idx = np.argsort(scores)[::-1][:n]
    # Exclure les résultats filtrés (score == -1)
    top_idx = [i for i in top_idx if scores[i] > -1.0]
    return [(documents[i], metadata[i], float(scores[i])) for i in top_idx]


# ── Utilitaires d'affichage ────────────────────────────────────────────────────
def highlight(text: str, terms: list) -> str:
    for term in terms:
        if len(term) < 3:
            continue
        text = re.sub(re.escape(term), lambda m: f"**{m.group(0)}**",
                      text, flags=re.IGNORECASE)
    return text


def excerpt(text: str, terms: list, window: int = 450) -> str:
    lower = text.lower()
    best = next(
        (lower.find(t.lower()) for t in terms if lower.find(t.lower()) >= 0),
        0
    )
    start = max(0, best - window // 3)
    end   = min(len(text), start + window)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


# Mots-clés indiquant une recherche de chiffres (tarifs, montants) → bonus aux chunks contenant des nombres
_QUERY_TARIF_MONTANT = re.compile(
    r"\b(tarif|tarifs|montant|montants|prix|barème|barèmes|coût|coûts|euro|euros|taux|cotisation|grille|quotient)\b",
    re.IGNORECASE
)
# Chunk contient au moins un nombre (améliore le ranking pour les questions tarifaires)
_CHUNK_HAS_NUMBER = re.compile(r"\d")
# Chunk évoque un montant (€, crédit, HT, TTC, "euro") → à inclure quand on cherche les coûts des travaux
_CHUNK_HAS_AMOUNT = re.compile(
    r"\d[\d\s]*(?:€|euro|euros|HT|TTC)|(?:crédit|montant|budget|alloué|ouvrir)[^\n]{0,80}\d|"
    r"\d[\d\s]{2,}(?:\.\d{2})?\s*(?:€|euro)",
    re.IGNORECASE
)
# Chunk parle de voirie / travaux publics (rue, chaussée, route)
_CHUNK_VOIRIE = re.compile(
    r"\b(travaux|voirie|chauss[eé]e|route|rue|réfection|enrobé)\b",
    re.IGNORECASE
)
# Chunk parle d'Horizon / logiciels métiers (pour prioriser ces passages en sortie)
_CHUNK_HORIZON = re.compile(
    r"\b(horizon|logiciel|logiciels|renouvellement|villages\s*cloud|DETR)\b",
    re.IGNORECASE
)
# Questions sur le château / Viollet-le-Duc / restauration patrimoniale
_QUERY_CHATEAU = re.compile(
    r"\b(ch[âa]teau|viollet|wyganowski|ouradou|restauration|restaur[eé]|m[eé]di[eé]val|patrimoine|"
    r"monument|napoléon\s*III|napolé|gothic|néo.gothique|fortification|rempart|donjon|"
    r"inspecteur\s+des\s+travaux|genie\s*civil|architecte|architecture|moyen.?[aâ]ge)\b",
    re.IGNORECASE
)
# Chunk parle du château ou de Viollet-le-Duc ou des acteurs du chantier
_CHUNK_CHATEAU = re.compile(
    r"\b(ch[âa]teau|viollet|wyganowski|ouradou|restauration|restaur[eé]|fortification|donjon|rempart|"
    r"patrimoine|monument|napoléon\s*III|m[eé]di[eé]val|gothic|inspecteur|chantier)\b",
    re.IGNORECASE
)

# Questions sur sujets récurrents (logiciels, voirie, contrats) → inclure les PV récents (2025, 2024, 2023)
_QUERY_RECENT_DELIB = re.compile(
    r"\b(logiciel|logiciels|horizon|contrat\s+m[eé]tier|renouvellement\s+contrat|"
    r"travaux|voirie|chauss[eé]e|route)\b",
    re.IGNORECASE
)

# Mots vides français exclus de la recherche exacte
_STOP_FR = {
    'les', 'des', 'une', 'que', 'qui', 'est', 'pas', 'par', 'sur',
    'pour', 'avec', 'dans', 'ont', 'ete', 'aux', 'mais', 'quels',
    'quelles', 'quand', 'comment', 'pourquoi', 'combien', 'quel',
    'leur', 'leurs', 'votre', 'notre', 'cette', 'cet', 'ces', 'ses',
    'plus', 'tout', 'tous', 'toutes', 'bien', 'aussi', 'tres',
    'elle', 'elles', 'ils', 'vous', 'nous', 'lui', 'fait', 'faire',
    'avoir', 'etre', 'autre', 'autres', 'entre', 'depuis', 'avant',
    'apres', 'pendant', 'pris', 'prises', 'vote', 'votes', 'votees',
    'quelles', 'prises', 'montant', 'montants',
}


# ── Recherche hybride pour l'agent (sémantique + exacte sur noms clés) ────────
def search_agent(question: str, embeddings, documents, metadata,
                 n: int = 15, year_filter: list = None, bm25=None):
    """
    Combine recherche hybride (sémantique + BM25) et recherche exacte filtrée sur les noms
    significatifs de la question (sans mots vides ni mots de question).
    Bonus pour les chunks contenant des chiffres quand la question porte sur tarifs/montants.
    """
    sem = search(question, embeddings, documents, metadata,
                 n=n, year_filter=year_filter, exact=False, bm25=bm25)

    # Extraire uniquement les mots porteurs de sens (≥ 4 chars, hors stop words)
    raw = [t.strip("'\".,?!") for t in re.split(r'\W+', question)]
    sig = [t for t in raw
           if len(t) >= 4
           and t.lower().replace('é','e').replace('è','e')
                        .replace('ê','e').replace('û','u') not in _STOP_FR]

    query_wants_figures = bool(_QUERY_TARIF_MONTANT.search(question))
    query_wants_voirie = bool(_QUERY_RECENT_DELIB.search(question))  # travaux, voirie, etc.

    def _score_with_bonus(doc, meta, score):
        # Bonus si la question porte sur tarifs/montants et le passage contient des chiffres
        if query_wants_figures and _CHUNK_HAS_NUMBER.search(doc):
            score = score + 0.04
        # Bonus pour les chunks issus de PDF (PV) quand la question porte sur voirie/travaux/montants
        fname = meta.get("filename", "")
        if (query_wants_figures or query_wants_voirie) and str(fname).lower().endswith(".pdf"):
            score = score + 0.05
        # Fort bonus pour les chunks "tableau" (barèmes, tarifs cantine/périscolaire) quand la question porte sur les chiffres
        if query_wants_figures and meta.get("is_table"):
            score = score + 0.12
        return (doc, meta, min(score, 1.0))

    seen: dict = {}
    if sig:
        focused = " ".join(sig)
        exact = search(focused, embeddings, documents, metadata,
                       n=n, year_filter=year_filter, exact=True, bm25=bm25)
        for doc, meta, score in exact:
            key = (meta.get("filename", ""), meta.get("chunk", 0))
            seen[key] = _score_with_bonus(doc, meta, score + 0.05)

    for doc, meta, score in sem:
        key = (meta.get("filename", ""), meta.get("chunk", 0))
        if key not in seen:
            seen[key] = _score_with_bonus(doc, meta, score)

    # Pour les questions sur logiciels, voirie, contrats : inclure des passages des PV récents (2025 prioritaire)
    if (year_filter is None or len(year_filter) == 0) and _QUERY_RECENT_DELIB.search(question):
        year_bonus = {2025: 0.14, 2024: 0.09, 2023: 0.06}  # 2025 fortement favorisé pour donner la situation à jour
        for y in (2025, 2024, 2023):
            extra = search(question, embeddings, documents, metadata, n=12, year_filter=[y], exact=False, bm25=bm25)
            for doc, meta, score in extra:
                key = (meta.get("filename", ""), meta.get("chunk", 0))
                if key not in seen:
                    seen[key] = _score_with_bonus(doc, meta, score + year_bonus[y])
        # Pour logiciels/Horizon : forcer l'inclusion de tous les chunks 2025 (puis 2024) qui parlent d'Horizon/logiciels,
        # pour que la réponse détaille la situation récente (2025) et pas seulement l'historique (ex. 2022).
        if re.search(r"\b(logiciel|logiciels|horizon|renouvellement)\b", question, re.IGNORECASE):
            for y in (2025, 2024):
                added_h = 0
                for doc, meta in zip(documents, metadata):
                    if added_h >= 25:
                        break
                    if meta.get("year") != str(y):
                        continue
                    if not str(meta.get("filename", "")).lower().endswith(".pdf"):
                        continue
                    if not _CHUNK_HORIZON.search(doc):
                        continue
                    key = (meta.get("filename", ""), meta.get("chunk", 0))
                    if key in seen:
                        continue
                    # 2025 très prioritaire pour détailler la situation actuelle
                    score_h = 0.58 if y == 2025 else 0.48
                    seen[key] = (doc, meta, score_h)
                    added_h += 1
            # Recherche sémantique ciblée en complément (2025/2024)
            for kw in ("logiciels métiers", "renouvellement contrat", "Horizon"):
                extra = search(kw, embeddings, documents, metadata, n=10, year_filter=[2025, 2024], exact=True, bm25=bm25)
                for doc, meta, score in extra:
                    key = (meta.get("filename", ""), meta.get("chunk", 0))
                    if key not in seen:
                        seen[key] = _score_with_bonus(doc, meta, score + 0.12)
            # Secours : inclure tout passage qui mentionne "Horizon" ou "logiciel" (toutes années).
            for kw in ("Horizon", "logiciel", "logiciels"):
                extra = search(kw, embeddings, documents, metadata, n=18, year_filter=None, exact=True, bm25=bm25)
                for doc, meta, score in extra:
                    key = (meta.get("filename", ""), meta.get("chunk", 0))
                    if key not in seen:
                        y = meta.get("year") or ""
                        bonus = 0.18 if y == "2025" else 0.12 if y == "2024" else 0.06
                        seen[key] = _score_with_bonus(doc, meta, score + bonus)
            # Force : parcourir toute la base et ajouter tout chunk qui mentionne Horizon/logiciel (PDF),
            # pour ne jamais exclure ces passages quand ils existent (ex. PV 2022).
            added_any = 0
            for doc, meta in zip(documents, metadata):
                if added_any >= 35:
                    break
                if not str(meta.get("filename", "")).lower().endswith(".pdf"):
                    continue
                if not _CHUNK_HORIZON.search(doc):
                    continue
                key = (meta.get("filename", ""), meta.get("chunk", 0))
                if key in seen:
                    continue
                y = meta.get("year") or ""
                score_force = 0.50 if y == "2025" else 0.42 if y == "2024" else 0.35
                seen[key] = (doc, meta, score_force)
                added_any += 1

    # Pour voirie/travaux/montant : forcer l'inclusion de chunks qui contiennent "voirie", "travaux", "crédit", "Armistice"
    if query_wants_voirie or query_wants_figures:
        for exact_query in ("voirie travaux", "voirie", "travaux", "crédit", "Armistice", "rue de l'Armistice"):
            exact_chunks = search(exact_query, embeddings, documents, metadata, n=10, year_filter=year_filter, exact=True, bm25=bm25)
            for doc, meta, score in exact_chunks:
                key = (meta.get("filename", ""), meta.get("chunk", 0))
                if key not in seen:
                    # Priorité aux PDF (PV) et aux chunks avec des chiffres
                    bonus = 0.08 if str(meta.get("filename", "")).lower().endswith(".pdf") else 0.04
                    if _CHUNK_HAS_NUMBER.search(doc):
                        bonus += 0.04
                    seen[key] = _score_with_bonus(doc, meta, score + bonus)

    # Expansion de contexte : pour chaque chunk trouvé, ajouter les voisins
    # immédiats (±1, ±2) du même fichier — capture les délibérations adjacentes
    all_by_key = {
        (m.get("filename", ""), m.get("chunk", 0)): (d, m)
        for d, m in zip(documents, metadata)
    }
    for (fname, chunk_idx), (_, _, score) in list(seen.items()):
        for delta in (-2, -1, 1, 2):
            nkey = (fname, chunk_idx + delta)
            if nkey in all_by_key and nkey not in seen:
                nd, nm = all_by_key[nkey]
                # Score décroissant avec la distance
                neighbor_score = max(0.0, score - 0.05 * abs(delta))
                seen[nkey] = (nd, nm, neighbor_score)

    # Travaux de voirie + montants des 2 dernières années : inclure explicitement les passages
    # (PV) qui parlent de voirie/travaux ET de montants pour que l'agent puisse les citer.
    if query_wants_voirie or query_wants_figures:
        last_2_years = {str(datetime.now().year), str(datetime.now().year - 1)}
        added_voirie = 0
        for doc, meta in zip(documents, metadata):
            if added_voirie >= 20:
                break
            fname = meta.get("filename", "")
            if not str(fname).lower().endswith(".pdf"):
                continue
            if meta.get("year") not in last_2_years:
                continue
            if not _CHUNK_VOIRIE.search(doc):
                continue
            if not _CHUNK_HAS_NUMBER.search(doc):
                continue
            key = (fname, meta.get("chunk", 0))
            if key in seen:
                continue
            # Priorité aux chunks qui contiennent un montant explicite (€, crédit, etc.)
            score_voirie = 0.52 if _CHUNK_HAS_AMOUNT.search(doc) else 0.45
            seen[key] = (doc, meta, score_voirie)
            added_voirie += 1

    # Quand la question porte sur les montants (travaux, voirie, budget) : ajouter les chunks
    # du même PV qui mentionnent des montants (€, crédit, HT, etc.) pour que le montant voté
    # soit fourni s'il figure ailleurs dans le procès-verbal (ex. rue de l'Armistice).
    pdf_files_in_context = {
        meta.get("filename") for _, meta, _ in seen.values()
        if str(meta.get("filename", "")).lower().endswith(".pdf")
    }
    if (query_wants_figures or query_wants_voirie) and pdf_files_in_context:
        added = 0
        # Plus de chunks financiers du même PV pour les questions voirie/montants (réponse plus complète)
        max_extra_amount_chunks = 22 if query_wants_voirie else 12
        for i, (doc, meta) in enumerate(zip(documents, metadata)):
            if added >= max_extra_amount_chunks:
                break
            fname = meta.get("filename", "")
            if fname not in pdf_files_in_context:
                continue
            key = (fname, meta.get("chunk", 0))
            if key in seen:
                continue
            if not _CHUNK_HAS_AMOUNT.search(doc) or not _CHUNK_HAS_NUMBER.search(doc):
                continue
            seen[key] = (doc, meta, 0.38)
            added += 1

    # Pour les questions sur le château / Viollet-le-Duc : forcer l'inclusion des chunks des
    # fichiers septentrion (livres openedition) qui traitent de l'histoire et de la restauration.
    if _QUERY_CHATEAU.search(question):
        added_ch = 0
        for doc, meta in zip(documents, metadata):
            if added_ch >= 30:
                break
            fname = str(meta.get("filename", ""))
            # Cibler en priorité les fichiers septentrion puis tout chunk qui parle du château
            is_septentrion = "septentrion" in fname.lower() or "chateau" in fname.lower()
            if not (is_septentrion or _CHUNK_CHATEAU.search(doc)):
                continue
            key = (fname, meta.get("chunk", 0))
            if key in seen:
                continue
            score_ch = 0.60 if is_septentrion else 0.45
            seen[key] = (doc, meta, score_ch)
            added_ch += 1
        # Recherches exactes ciblées sur mots-clés château
        for kw in ("Viollet-le-Duc", "restauration château", "château Pierrefonds", "fortification"):
            extra = search(kw, embeddings, documents, metadata, n=12, year_filter=None, exact=True, bm25=bm25)
            for doc, meta, score in extra:
                key = (meta.get("filename", ""), meta.get("chunk", 0))
                if key not in seen:
                    seen[key] = (doc, meta, score + 0.10)

    merged = sorted(seen.values(), key=lambda x: x[2], reverse=True)
    # Pour les questions sur le château : placer les chunks septentrion en tête
    if _QUERY_CHATEAU.search(question):
        chateau_first = [x for x in merged if _CHUNK_CHATEAU.search(x[0]) or
                         "septentrion" in str(x[1].get("filename", "")).lower()]
        others = [x for x in merged if x not in chateau_first]
        merged = chateau_first + others
    # Pour les questions sur Horizon/logiciels : placer les passages qui en parlent en tête (2025 avant 2024 avant le reste).
    if re.search(r"\b(logiciel|logiciels|horizon|renouvellement)\b", question, re.IGNORECASE):
        horizon_first = [x for x in merged if _CHUNK_HORIZON.search(x[0])]
        others = [x for x in merged if x not in horizon_first]
        # 2025 en premier, puis 2024, puis les autres années
        def _year_prio(t):
            y = (t[1].get("year") or "").strip()
            return (0 if y == "2025" else 1 if y == "2024" else 2, -(t[2]))
        horizon_first.sort(key=_year_prio)
        merged = horizon_first + others
    merged = merged[:n]
    return [(doc, meta, min(score, 1.0)) for doc, meta, score in merged]


# ── Agent RAG : appel Claude avec streaming ────────────────────────────────────
SYSTEM_AGENT = """Tu es un assistant spécialisé dans l'analyse des procès-verbaux \
du Conseil Municipal de Pierrefonds (Oise, 60350, France).

## Contexte municipal de Pierrefonds

**Conseil municipal (19 membres) :**
- Maire : Florence Demouy (vice-présidente tourisme/culture/communication à la CCLoise)
- Adjoints : Jean-Jacques Carretero (voirie, bâtiments, urbanisme, sécurité),
  Emmanuelle Lemaitre (affaires sociales, santé, associations, événements),
  Romain Ribeiro (finances)
- Conseillers délégués : Hélène Defossez (culture), Stéphane Dutilloy (espaces publics),
  Laetitia Pierron (scolaire/périscolaire)
- Conseillers : Virginie Anthony, Elsa Carrier, Marie-Alice Debuisser, Karine Duteil,
  Catherine Gevaert, Gérard Lannier, Michel Leblanc, Joachim Lüder, Gilles Papin,
  Ronan Tanguy, Jean-Claude Thuillier, Philippe Toledano

**Commissions municipales (7) :** Finances, Circulation/stationnement, Transition écologique,
Protection/sécurité, Urbanisme, Vie scolaire/périscolaire, Vie culturelle/associations.
+ Commission d'appel d'offres (3 titulaires, 2 suppléants).

**Intercommunalité :**
- CCLoise : Communauté de Communes des Lisières de l'Oise (ccloise.com)
- SE60 / SIED : Syndicat d'Énergie de l'Oise (réseau électrique, éclairage public)
- SMOA : Syndicat Mixte Oise-Aronde (gestion de l'eau)
- SIVOC : Syndicat Intercommunal à Vocation Culturelle (école de musique et danse)
- SMIOCCE : Syndicat Mixte Intercommunal des Classes d'Environnement (sorties scolaires)

**Équipements et lieux clés :**
- École : Groupe Scolaire Louis Lesueur, 7 Rue du 8 mai 1945
- Collège : Louis Bouland à Couloisy ; Lycées Pierre d'Ailly & Mireille Grenet à Compiègne
- Gymnase : 7 Rue du Martreuil ; Stade municipal : Rue Viollet-le-Duc
- Tennis : 17 Rue du Beaudo ; Skate park : Rue du Bois d'Haucourt
- Foyer Napoléon (salle communautaire) ; Bibliothèque municipale
- Massifs forestiers : Bois d'Haucourt, Vertefeuille
- Château de Pierrefonds (restauré par Viollet-le-Duc sous Napoléon III, 1857)

**Éléments historiques :** Première mention médiévale, château reconstruit par Louis duc
d'Orléans (1390), démoli en 1618 (Richelieu), acquis par Napoléon Ier (1811), restauré
par Viollet-le-Duc dès 1857. Sources thermales (1846), gare ouverte 1884, fermée 1940.
Sous le Second Empire : station thermale connue sous "Pierrefonds-les-Bains". Devise : "Qui veult, peult".

**Géographie & démographie :**
- Habitants : ~1 882 Pétrifontains/Pétrifontaines (INSEE 60491) · Superficie : 22 km² · Alt. moy. 80 m
- Canton de Compiègne-2, arrondissement de Compiègne (à 13 km à l'ouest)
- Communes voisines : Saint-Étienne-Roilaye, Retheuil, Cuise-la-Motte, Trosly-Breuil, Chelles
- Hydrographie : ru de Berne, étang de Vertefeuilles (0,7 ha), ru de la Fontaine Porchers
- Journal municipal : L'Écho de Pierrefonds-Palesne (parution ~trimestrielle)

**Actualités locales récentes (issues de la presse et du site mairie) :**
- Budget participatif : 1ʳᵉ édition lancée en avril 2025 (habitants/associations proposent des projets)
- Travaux rue de l'Armistice : études 2021-2022, subventions déposées 2023, phase active en cours
- Travaux rue de l'Impératrice Eugénie : interdiction stationnement août–oct. 2024
- Stationnement : zone bleue mise en place place de l'Hôtel de Ville et rue Saint-Louis
- Train touristique : rétabli depuis avril 2022
- Incendie café du Commerce (place principale, août 2023)
- Festival L'Enceinte (musique) : 1ʳᵉ édition prévue au pied du château en août 2026
- Trail du Château de Pierrefonds : 27 km / 600 m D+ et 13 km / 350 m D+ (arrivée Institut Charles Quentin)

## Règles strictes
1. Tu réponds en priorité à partir des passages fournis entre balises <source>. \
   Exception : si la question porte sur l'histoire de Pierrefonds, le château, Viollet-le-Duc ou un sujet \
   patrimonial/touristique lié à Pierrefonds, et que les passages ne contiennent pas d'information pertinente, \
   tu peux répondre en t'appuyant sur tes connaissances générales. Dans ce cas, commence par préciser : \
   « Les procès-verbaux du conseil municipal ne traitent pas directement de ce sujet. Voici ce que je sais : »
2. Si un passage ne traite pas directement du sujet de la question, ignore-le.
3. Ne cite un montant ou un chiffre QUE s'il est explicitement associé au sujet \
   exact de la question dans le passage.
4. Si l'information est absente ou insuffisante dans les sources ET que le sujet n'est pas lié à l'histoire \
   ou au patrimoine de Pierrefonds, dis-le clairement et brièvement. Ne liste jamais \
   tous les numéros de source (ex. [1, 2, 3, ... 28]) pour dire que l'info manque ; formule en une phrase.
4b. Pour les questions sur les montants (travaux de voirie, budget, délibérations) : fournis une réponse \
   complète avec les éléments financiers disponibles. Parcours TOUS les passages fournis pour repérer \
   tout chiffre (€, HT, TTC, euros, crédit, subvention) lié à la voirie, aux travaux ou au budget ; \
   cite-les avec leur source [N]. Si aucun montant pertinent n'apparaît dans les extraits, indique alors \
   où le trouver : procès-verbaux complets sur mairie-pierrefonds.fr (Vie municipale > Conseil municipal). \
   Maire-adjoint voirie : Jean-Jacques Carretero.
4c. Tarifs et barèmes : si les passages disent par exemple « les tarifs sont les suivants » ou \
   « barème selon quotient familial » mais ne contiennent pas les montants ou le tableau, \
   indique explicitement que les chiffres détaillés ne figurent pas dans les extraits fournis \
   et renvoie l'utilisateur vers la source (lien PDF ou page mairie-pierrefonds.fr) pour consulter \
   le barème complet. Les tableaux (cantine, périscolaire, etc.) sont désormais mieux indexés ; \
   si un passage contient un tableau avec des chiffres, cite-les avec leur source.
4d. Sujets récurrents (logiciels, Horizon, contrats) : pour les questions sur Horizon ou les logiciels \
   métiers, utilise TOUS les passages qui mentionnent Horizon, logiciel, renouvellement ou DETR. \
   Si des passages de 2025 sont fournis, tu DOIS les détailler en priorité (décisions, montants, renouvellement). \
   Puis détaille la plus récente autre année (ex. 2024), puis l'historique (ex. 2022). \
   Si les passages ne contiennent que des délibérations plus anciennes (ex. 2022), réponds quand même \
   en t'appuyant sur elles et indique que « les extraits fournis concernent notamment la délibération de [date] » \
   avec les montants et décisions. \
   INTERDICTION : Tu ne dois JAMAIS écrire « il n'y a aucune information sur les logiciels Horizon dans les passages fournis » \
   dès qu'au moins un passage contient le mot « Horizon » ou « logiciel » ; dans ce cas, tu DOIS répondre en t'appuyant sur ces passages.
4e. Questions sur une personne (élu, candidat, conseiller) : quand la question porte sur le rôle \
   ou l'action d'une personne au conseil municipal, NE TE CONTENTE PAS de dire qu'elle était « présente » \
   aux séances. Cherche dans les passages : \
   (1) Son titre ou sa fonction : maire, adjoint(e), conseiller(e) délégué(e), président(e) de commission, etc. \
   (2) Ses délégations : voirie, finances, scolaire, urbanisme, culture, etc. \
   (3) Ses interventions ou prises de position concrètes : a-t-elle voté contre ? s'est-elle abstenue ? \
       a-t-elle présenté une délibération ? été rapporteur ? proposé un amendement ? \
   (4) Les commissions ou syndicats où elle siège (CCLoise, SE60, SMOA, SIVOC, etc.). \
   (5) Les sujets/dossiers auxquels elle est associée dans les passages. \
   Structure la réponse : d'abord le rôle/fonction, puis les actions/dossiers marquants par ordre chronologique. \
   Si les passages ne contiennent que des listes de présence sans autre information sur cette personne, \
   dis-le en UNE phrase et indique les années de présence constatées (ex. « présent(e) aux séances de 2016 à 2023 »). \
   Ne liste JAMAIS tous les numéros de source pour une simple présence ; regroupe (ex. [1-28] ou « dans l'ensemble des PV fournis »). \
   Cherche aussi si la personne a été élue secrétaire de séance ou désignée dans un vote nominatif. \
   IMPORTANT : tu disposes déjà de l'intégralité des procès-verbaux indexés. Ne renvoie JAMAIS l'utilisateur \
   vers le site de la mairie ou vers d'autres documents pour « plus de détails » sur une personne. \
   Si l'information n'est pas dans les passages fournis, dis simplement que les procès-verbaux indexés \
   ne contiennent pas de détail supplémentaire sur cette personne au-delà de sa présence aux séances.
4f. Travaux de voirie et montants : donne une réponse complète avec des éléments financiers quand c'est possible. \
   (1) Résume ce que disent les passages : quels travaux (ex. rue de l'Armistice), où, contexte (circulation alternée, etc.) avec la source [N]. \
   (2) Cite tout montant, crédit, subvention ou budget trouvé dans les passages (€, HT, TTC) avec sa source [N]. \
   (3) Si le montant exact n'est pas dans les extraits, indique-le clairement et renvoie vers les procès-verbaux complets (mairie, Vie municipale > Conseil municipal). \
   Structure la réponse (titres courts ou paragraphes) pour que les éléments financiers soient visibles ; ne te contente pas d'un seul paragraphe vague.
5. Tu réponds toujours en français, de façon détaillée et structurée. \
   Pour les questions historiques, patrimoniales ou techniques (château, Viollet-le-Duc, métiers, architecture, restauration…), \
   développe ta réponse en plusieurs paragraphes thématiques : contexte, méthodes, acteurs, anecdotes, chronologie, \
   résultats. N'hésite pas à écrire 400 à 800 mots si le sujet le permet.
6. Pour chaque affirmation, indique le numéro de la source entre crochets \
   (ex : [1], [3]) — utilise uniquement le chiffre, rien d'autre.
7. N'écris JAMAIS les balises <source> ou </source> dans ta réponse.
8. Le contexte municipal ci-dessus est fourni à titre informatif pour comprendre \
   les acronymes et les acteurs — n'en tire aucune conclusion non présente dans les sources. \
   Exception : pour les sujets historiques et patrimoniaux (château, Viollet-le-Duc, histoire de Pierrefonds), \
   tu peux utiliser tes connaissances générales si les passages ne fournissent pas l'information, \
   en le signalant explicitement.
9. Les sources dont le fichier contient « septentrion » ou « Web » correspondent à des livres ou sites \
   web sur Pierrefonds (ex. "Viollet-le-Duc et Pierrefonds", éditions Septentrion/OpenEdition). \
   Ces sources sont valides et fiables pour l'histoire du château. Appuie-toi dessus en priorité \
   pour toute question sur la restauration, l'architecture ou l'histoire du château."""


def ask_claude_stream(question: str, passages: list):
    """
    Générateur qui streame la réponse via l'API Groq (gratuite).
    Lève ValueError si la clé API est manquante ou si groq n'est pas installé.
    """
    if not _GROQ_OK:
        raise ValueError("Le package `groq` n'est pas installé. Lancez : `pip install groq`")

    try:
        api_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        api_key = ""
    if not api_key:
        raise ValueError(
            "Clé API Groq manquante. "
            "Ajoutez `GROQ_API_KEY = \"gsk_...\"` dans `.streamlit/secrets.toml`. "
            "Clé gratuite sur : https://console.groq.com/keys"
        )

    context_parts = []
    for i, (doc, meta, score) in enumerate(passages, 1):
        fname = meta.get("filename", "?")
        context_parts.append(f"<source id=\"{i}\" fichier=\"{fname}\">\n{doc}\n</source>")
    context = "\n\n".join(context_parts)

    # Quand la question porte sur Horizon/logiciels et qu'au moins un passage en parle, forcer le LLM à s'en servir
    question_about_horizon = bool(re.search(r"\b(horizon|logiciel|logiciels)\b", question, re.IGNORECASE))
    passages_mention_horizon = any(_CHUNK_HORIZON.search(doc) for doc, _, _ in passages)
    has_2025 = any((m.get("year") or "").strip() == "2025" for _, m, _ in passages)
    horizon_note = ""
    if question_about_horizon and passages_mention_horizon:
        horizon_note = (
            "IMPORTANT : Au moins un des passages ci-dessous mentionne les logiciels Horizon ou les logiciels métiers. "
            "Tu DOIS t'appuyer sur ces passages pour répondre. Il est interdit d'écrire qu'il n'y a aucune information sur Horizon."
        )
        if has_2025:
            horizon_note += " Des passages de 2025 sont présents : détaille-les en priorité (décisions, montants, renouvellement, DETR)."
        horizon_note += "\n\n"

    user_msg = (
        f"Question : {question}\n\n"
        f"{horizon_note}"
        f"Passages pertinents issus des procès-verbaux :\n\n{context}\n\n"
        "Réponds à la question en te basant exclusivement sur ces passages."
    )

    client = _Groq(api_key=api_key)
    stream = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1500,
        messages=[
            {"role": "system", "content": SYSTEM_AGENT},
            {"role": "user",   "content": user_msg},
        ],
        stream=True,
    )
    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content


# ── Post-traitement : remplacement des références sources par des liens ─────────
def _liens_sources(text: str, passages: list) -> str:
    """
    Remplace dans le texte :
    - les balises <source id="N" ...> et </source> résiduelles
    - les noms de fichiers PDF cités par le LLM
    par des liens Markdown cliquables ouvrant le PDF dans un nouvel onglet.
    """
    # Mapping id (1-based) → (filename, url, icon)
    id_map = {}
    fname_map = {}
    for i, (_, meta, _) in enumerate(passages, 1):
        fname = meta.get("filename", "")
        source_url = meta.get("source_url", "")
        if source_url and _safe_source_url(source_url):
            url, icon = _safe_source_url(source_url), "🌐"
        else:
            # Documents locaux (.md extraits de PDF) : pas d'URL servable → pas de lien
            url, icon = "#", "📝"
        id_map[str(i)] = (fname, url, icon)
        if fname:
            fname_map[fname] = url

    def _make_link(sid):
        if sid in id_map:
            fname, url, icon = id_map[sid]
            # Dans le texte : uniquement le numéro [1], [2], [3] (cliquable)
            return f"[{sid}]({url})"
        return f"[{sid}]"

    # 0a. Remplacer les références [N] produites par le LLM (format principal)
    #     (?!\() évite de remplacer les liens Markdown déjà formés [texte](url)
    text = re.sub(r'\[(\d+)\](?!\()', lambda m: _make_link(m.group(1)), text)

    # 0b. Remplacer __N__ (le LLM utilise parfois le bold Markdown pour les citations)
    text = re.sub(r'__(\d+)__', lambda m: _make_link(m.group(1)), text)

    # 1. Remplacer <source id="N" ...> résiduels (au cas où le LLM en échappe)
    text = re.sub(r'<source\s+id=["\'](\d+)["\'][^>]*>',
                  lambda m: _make_link(m.group(1)), text)

    # 2. Supprimer les balises <source> / </source> restantes
    text = re.sub(r'</source>', "", text)
    text = re.sub(r'<source[^>]*>', "", text)

    return text


def _bloc_references(text: str, passages: list) -> str:
    """Construit le bloc « Références » en fin de réponse : uniquement les sources citées dans le texte."""
    if not passages:
        return ""
    # Extraire les numéros [N] ou [N](url) mentionnés dans le texte
    nums = sorted({int(m) for m in re.findall(r"\[(\d+)\]", text) if 1 <= int(m) <= len(passages)})
    if not nums:
        return ""
    lines = ["**Références**", ""]
    for i in nums:
        _, meta, _ = passages[i - 1]
        fname = meta.get("filename", "")
        source_url = meta.get("source_url", "")
        label = (fname or meta.get("rel_path", "") or "").replace(".pdf", "").replace(".md", "").replace("[Web] ", "")
        if source_url and _safe_source_url(source_url):
            url = _safe_source_url(source_url)
            lines.append(f"Passage {i} : [{label}]({url})")
        else:
            # Document local (PV, L'ECHO...) : pas de lien, juste le nom
            lines.append(f"Passage {i} : 📝 {label}")
    return "\n".join(lines)


# ── Chemins du guide utilisateur (static prioritaire pour déploiement) ─────────
GUIDE_MD = APP_DIR / "static" / "Guide-utilisateurs.md"
if not GUIDE_MD.exists():
    GUIDE_MD = APP_DIR / "docs" / "Guide-utilisateurs.md"

# ── Chemins du guide technique (static prioritaire) ─────────────────────────────
TECH_ARCH_MD = APP_DIR / "static" / "Architecture-technique.md"
if not TECH_ARCH_MD.exists():
    TECH_ARCH_MD = APP_DIR / "docs" / "Architecture-technique.md"
TECH_RAG_MD = APP_DIR / "static" / "Recherche-et-agent-RAG.md"
if not TECH_RAG_MD.exists():
    TECH_RAG_MD = APP_DIR / "docs" / "Recherche-et-agent-RAG.md"


@st.dialog("Guide Utilisateur", width="large", icon="📖")
def guide_utilisateur():
    """Affiche la documentation utilisateur (Markdown) dans une popup."""
    if not GUIDE_MD.exists():
        st.warning("Le fichier Guide-utilisateurs.md est introuvable. Exécutez ALL.bat pour copier la doc vers static.")
        return
    try:
        content = GUIDE_MD.read_text(encoding="utf-8")
        st.markdown(content)
    except Exception as e:
        st.error(f"Impossible de charger le guide : {e}")


@st.dialog("Technical Guide", width="large", icon="🔧")
def technical_guide():
    """Affiche la documentation technique (Architecture + Recherche/agent RAG) dans une popup."""
    if not TECH_ARCH_MD.exists() and not TECH_RAG_MD.exists():
        st.warning("Les fichiers de documentation technique sont introuvables. Exécutez ALL.bat pour les copier vers static.")
        return
    try:
        if TECH_ARCH_MD.exists():
            with st.expander("Architecture technique", expanded=True):
                st.markdown(TECH_ARCH_MD.read_text(encoding="utf-8"))
        if TECH_RAG_MD.exists():
            with st.expander("Recherche sémantique et agent RAG", expanded=True):
                st.markdown(TECH_RAG_MD.read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"Impossible de charger le guide technique : {e}")


# ── Popup À propos ─────────────────────────────────────────────────────────────
@st.dialog("À propos", width="medium", icon="ℹ️")
def about_casimir():
    st.markdown("""
**Bienvenue à Casimir!**

Casimir est un agent créé par intelligence artificielle.  
Son but est de tout connaître sur notre belle ville de Pierrefonds et de converser avec nous pour répondre à nos questions.

Pour cela il a « appris » à partir de tous les documents publics disponibles : documents de la Mairie, sites Web, journaux.

Je voulais m'entraîner sur ce domaine — une sorte de travaux pratiques pour m'exercer sur les technologies : Cursor pour le code, Anthropic Claude Opus 4.6 pour le modèle, Groq pour l'agent.

**Rencontrez Casimir ici :** [https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app/](https://mymairie-ksbry6thyvm8uddujy289c.streamlit.app/)

**Écrivez-lui à** [casimir.pierrefonds@outlook.com](mailto:casimir.pierrefonds@outlook.com)
""")


@st.dialog("Base des recherches", width="large", icon="🔑")
def admin_searches_db():
    """Affiche la table SQLite des recherches (IP, timestamp, requête) — visible uniquement via URL admin."""
    try:
        _init_searches_db()
        with sqlite3.connect(SEARCHES_DB) as conn:
            rows = conn.execute(
                "SELECT ip, timestamp, query FROM searches ORDER BY timestamp DESC"
            ).fetchall()
        if not rows:
            st.info("Aucune recherche enregistrée.")
            return
        # Tableau : IP, Date/Heure (Paris), Recherche
        tz_paris = ZoneInfo("Europe/Paris")
        data = [
            {
                "IP": r[0] or "",
                "Date / Heure": datetime.fromtimestamp(r[1], tz=tz_paris).strftime("%Y-%m-%d %H:%M:%S") if r[1] else "",
                "Recherche": (r[2] or "")[:500],
            }
            for r in rows
        ]
        st.dataframe(data, use_container_width=True, height=400)
        st.caption(f"Total : {len(data)} enregistrement(s)")
    except Exception as e:
        st.error(f"Impossible de charger la base : {e}")


def export_searches_csv() -> None:
    """
    Exporte la table des recherches au format CSV brut.
    Utilisé par un workflow GitHub (curl) pour prendre un snapshot.
    """
    try:
        _init_searches_db()
        with sqlite3.connect(SEARCHES_DB) as conn:
            rows = conn.execute(
                "SELECT ip, timestamp, query FROM searches ORDER BY timestamp ASC"
            ).fetchall()
        tz_paris = ZoneInfo("Europe/Paris")
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(["ip", "timestamp_paris_iso", "query"])
        for ip, ts, q in rows:
            if ts:
                dt = datetime.fromtimestamp(ts, tz=tz_paris).isoformat()
            else:
                dt = ""
            # Aplatir les retours à la ligne dans la requête
            qq = (q or "").replace("\r", " ").replace("\n", " ")
            writer.writerow([ip or "", dt, qq])
        csv_content = buf.getvalue()
        # Sortie minimale : un seul bloc de texte, facile à récupérer via curl
        st.text(csv_content)
    except Exception as e:
        st.error(f"Impossible d'exporter la base des recherches : {e}")
        st.stop()


# ── Interface principale ───────────────────────────────────────────────────────
def main():
    if "current_section" not in st.session_state:
        st.session_state["current_section"] = "home"

    # Intercepter les liens de noms propres (?q=...) — AVANT le routage de section
    _q_link = st.query_params.get("q", "")
    if _q_link and not st.session_state.get("agent_auto_search"):
        st.session_state["agent_auto_search"] = _q_link
        st.session_state["agent_question"] = _q_link
        st.session_state["current_section"] = "agent"
        st.query_params.clear()
        st.rerun()

    # IP publique côté client (même source que le bandeau : api.ipify.org via st_javascript)
    if "client_public_ip" not in st.session_state and _ST_JS_OK:
        ip_js = st_javascript(
            """(async function(){
                try {
                    const r = await fetch('https://api.ipify.org?format=json');
                    const d = await r.json();
                    return d.ip || null;
                } catch(e) { return null; }
            })()""",
            "Récupération de l'IP…",
        )
        if ip_js and isinstance(ip_js, str) and ip_js.strip():
            st.session_state["client_public_ip"] = ip_js.strip()
        elif ip_js is None:
            st.stop()

    admin = is_admin()
    # Mode export CSV pour GitHub Actions : ?admin=TOKEN&export_searches=1
    export_flag = st.query_params.get("export_searches", "")
    if admin and str(export_flag).strip() == "1":
        export_searches_csv()
        return

    show_sidebar = st.session_state["current_section"] == "search"
    st.set_page_config(
        page_title="Casimir",
        page_icon="🏛️",
        layout="wide",
        initial_sidebar_state="expanded" if show_sidebar else "collapsed",
    )

    st.markdown(
        """<style>
        [data-testid='stToolbar']         { display: none !important; }
        [data-testid='stAppDeployButton'] { display: none !important; }
        .stDeployButton                   { display: none !important; }
        #MainMenu                         { display: none !important; }
        footer                            { display: none !important; }
        [data-testid='stSidebarNav']          { display: none !important; }
        [data-testid='stSidebarNavItems']     { display: none !important; }
        [data-testid='stSidebarNavSeparator'] { display: none !important; }
        [data-testid='stSidebar'] > div:first-child { padding-top: 0 !important; }
        section[data-testid='stSidebar'] > div { padding-top: 0 !important; }
        [data-testid='stSidebarContent'] { padding-top: 0 !important; }
        [data-testid='stSidebarContent'] > div:first-child { padding-top: 0 !important; margin-top: 0 !important; }
        .home-card { background:#fff; border:1px solid #ddd; border-radius:12px; padding:1.5rem;
                     box-shadow:0 2px 8px rgba(0,0,0,0.06); transition:box-shadow 0.2s; }
        .home-card:hover { box-shadow:0 4px 12px rgba(44,95,45,0.15); }
        .home-card h3 { color:#2c5f2d; margin:0 0 0.5rem; font-size:1.1rem; }
        .home-card p { color:#666; margin:0; font-size:0.9rem; line-height:1.4; }
        .top-banner { background:#f0f2f6; padding:0.5rem 1rem; border-radius:6px; margin-bottom:1rem; }
        /* Espace au-dessus du bandeau pour ne pas tronquer */
        [data-testid="stAppViewContainer"] > section { padding-top: 0 !important; }
        [data-testid="stAppViewContainer"] .block-container { padding-top: 0.75rem !important; max-width: 100% !important; }
        section[data-testid="stSidebar"] + div .block-container { padding-top: 0.75rem !important; }
        /* Bandeau : padding interne, contenu ne touche pas les bords */
        [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]:first-child { margin-bottom: 0.5rem !important; padding: 0.5rem 0.75rem !important; box-sizing: border-box !important; }
        [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]:first-child [data-testid="stVerticalBlock"] { padding-top: 0.25rem !important; padding-bottom: 0.25rem !important; }
        [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]:first-child .stButton button { padding-top: 0.4rem !important; padding-bottom: 0.4rem !important; white-space: nowrap !important; }
        [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]:first-child .stButton button * { white-space: nowrap !important; }
        </style>""",
        unsafe_allow_html=True,
    )
    # Masquage sidebar quand pas sur Recherche + masquage éléments Streamlit
    _show_sb = st.session_state["current_section"] == "search"
    components.html(f"""
    <script>
    (function() {{
        const showSidebar = {str(_show_sb).lower()};
        const hide = () => {{
            const sel = [
                '[data-testid="stAppDeployButton"]',
                '[data-testid="stToolbar"]',
                '.stDeployButton',
                '#MainMenu',
                'footer',
                '[data-testid="stSidebarNav"]',
                '[data-testid="stSidebarNavItems"]',
                '[data-testid="stSidebarNavSeparator"]'
            ];
            sel.forEach(s => {{
                window.parent.document.querySelectorAll(s)
                    .forEach(el => {{ el.style.display = 'none'; }});
            }});
            if (!showSidebar) {{
                const sb = window.parent.document.querySelector('section[data-testid="stSidebar"]');
                if (sb) sb.style.display = 'none';
            }}
        }};
        hide();
        new MutationObserver(hide).observe(
            window.parent.document.body,
            {{ childList: true, subtree: true }}
        );
    }})();
    </script>
    """, height=0)

    if not DB_DIR.exists():
        st.error("Base vectorielle introuvable. Lancez d'abord : `python ingest.py`")
        st.stop()

    admin = is_admin()
    embeddings, documents, metadata, bm25 = load_db()
    # Détecter si la base contient des chunks issus de procès-verbaux (CM-*, compte-rendu-*, PV*)
    _PV_PATTERNS = ("cm-", "compte-rendu-", "pv-", "pv ", "-pv.", "lecho-", "l'echo")
    def _is_pv_meta(m: dict) -> bool:
        fn = str(m.get("filename", "")).lower()
        return any(fn.startswith(p) or p in fn for p in _PV_PATTERNS)
    _pv_filenames = {m.get("filename") or m.get("rel_path") for m in metadata if _is_pv_meta(m)}
    _pv_filenames.discard(None)
    base_has_pdfs = len(_pv_filenames) > 0   # conservé pour compatibilité des conditions existantes
    if admin:
        base_desc = f"**{len(documents)} passages**" + (f" (dont {len(_pv_filenames)} PV/délibération(s))" if base_has_pdfs else " (sites web uniquement, PVs non indexés)")
        st.caption(f"Base indexée : {base_desc} · 🔑 Mode admin")

    # ── Listes électorales ────────────────────────────────────────────────────
    listes_electorales = []  # [(nom_liste, [noms]), ...]
    _liste_file = APP_DIR / "liste electorale.txt"
    if _liste_file.exists():
        try:
            _raw = _liste_file.read_text(encoding="utf-8").splitlines()
            _cur_name, _cur_noms = None, []
            _need_name = False  # le nom de liste est sur la ligne suivante
            for _line in _raw:
                _line = _line.strip()
                if _line.lower().startswith("liste "):
                    if _cur_name and _cur_noms:
                        listes_electorales.append((_cur_name, _cur_noms))
                    # ex: "Liste 1 : AUTREMENT et ENSEMBLE" ou "Liste 2 : Poursuivons ..."
                    _after = _line.split(":", 1)[1].strip() if ":" in _line else ""
                    if _after:
                        _cur_name = _after
                        _need_name = False
                    else:
                        _cur_name = _line
                        _need_name = True
                    _cur_noms = []
                elif _line and _need_name:
                    _cur_name = _line
                    _need_name = False
                elif _line:
                    _cur_noms.append(_line)
            if _cur_name and _cur_noms:
                listes_electorales.append((_cur_name, _cur_noms))
        except Exception:
            pass

    # ── Bandeau supérieur (une ligne, compact) ─────────────────────────────────
    commit_date, _ = get_git_info()
    total_today = get_searches_today_count()
    remaining = rate_limit_get_remaining()
    max_display = rate_limit_get_max_for_display()
    remaining_str = "∞" if remaining is None else f"{remaining}/{max_display}"
    with st.container(border=True):
        c_nav, c_mail_deploy, c_stats = st.columns([3, 2.2, 1.4])
        with c_nav:
            nav_cols = 5 if admin else 3
            btn_cols = st.columns(nav_cols)
            with btn_cols[0]:
                if st.button("🏠 Accueil", key="banner_accueil"):
                    st.session_state["current_section"] = "home"
                    st.rerun()
            with btn_cols[1]:
                if st.button("ℹ️ À propos", key="banner_about"):
                    about_casimir()
            with btn_cols[2]:
                if st.button("📖 Guide\u00a0utilisateur", key="banner_guide"):
                    guide_utilisateur()
            if admin:
                with btn_cols[3]:
                    if st.button("🔧 Technical\u00a0Guide", key="banner_tech_guide"):
                        technical_guide()
                with btn_cols[4]:
                    if st.button("🔑 ADMIN", key="banner_admin"):
                        admin_searches_db()
        with c_mail_deploy:
            st.markdown(
                '<div style="text-align:left;font-size:0.9rem;line-height:1.5">'
                '<p style="margin:0;padding:0">Email : <a href="mailto:casimir.pierrefonds@outlook.com">casimir.pierrefonds@outlook.com</a></p>'
                f'<p style="margin:0;padding:0"><strong>Déployé le</strong> {commit_date}</p>'
                '</div>',
                unsafe_allow_html=True,
            )
        with c_stats:
            st.components.v1.html(
                f"""
                <div style="font-size:0.85rem;margin:0;padding:0.35rem 0;min-height:1.6rem;display:flex;align-items:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;box-sizing:border-box">
                    <span><b>🌐</b> <span id="banner-pubip">…</span> · <b>Rech. :</b> {total_today} (auj.) · {remaining_str}</span>
                </div>
                <script>
                (function() {{
                    var el = document.getElementById('banner-pubip');
                    if (!el) return;
                    fetch('https://api.ipify.org?format=json').then(function(r) {{ return r.json(); }})
                    .then(function(d) {{ el.textContent = d.ip || '—'; }})
                    .catch(function() {{ el.textContent = '—'; }});
                }})();
                </script>
                """,
                height=40,
            )

    # ── Sidebar (uniquement sur section Recherche) ─────────────────────────────
    if _show_sb:
        with st.sidebar:
            st.markdown('<p style="font-weight:600;margin:0 0 0.4rem 0;padding:0">Thèmes</p>', unsafe_allow_html=True)
            for i, (label, tq) in enumerate(THEMES.items()):
                if st.button(label, use_container_width=True, key=f"theme_{i}"):
                    st.session_state["current_section"] = "search"
                    st.session_state["_theme_query"] = tq
                    st.rerun()

    # ════════════════════════════════════════════════════════════════════════════
    # PAGE D'ACCUEIL — 4 cartes
    # ════════════════════════════════════════════════════════════════════════════
    if st.session_state["current_section"] == "home":
        st.title("Demande à Casimir!")
        st.subheader("Tout ce que tu veux savoir sur Pierrefonds grâce à notre Agent Intelligence Artificielle")
        st.markdown("<br>", unsafe_allow_html=True)

        CARDS = [
            ("🤖", "Interroger l'Agent Casimir", "Posez une question en langage naturel. **Casimir** a lu beaucoup d'articles et de comptes rendus sur **Pierrefonds**, il synthétise une réponse pour vous ! **Attention, comme chaque IA, il peut se tromper !** Vous avez accès aux sources pour vérifier. **Casimir** apprend tous les jours, mais doit se reposer de temps en temps pour regagner des crédits des fournisseurs d'IA … Vous avez quelques exemples ci-dessous. Je travaille à améliorer les réponses, à affiner les modèles d'IA.", "agent"),
            ("📊", "Statistiques des séances du Conseil Municipal", "Graphiques : délibérations par année, types de vote, durée des séances, présence des conseillers.", "stats"),
            ("🔍", "Recherche dans la base de connaissance", "Recherche sémantique dans les comptes rendus et toute la base de connaissance. Filtres par année, mode exact, suggestions.", "search"),
            ("📄", "Sources et Documents", "Liste des sources utilisées par Casimir et la recherche sémantique.", "docs"),
        ]
        if listes_electorales:
            CARDS.insert(1, ("🗳️", "Élections municipales", "Découvrez les candidats des 2 listes et interrogez Casimir sur leur rôle passé au conseil municipal.", "elections"))
        col1, col2 = st.columns(2)
        for i, (icon, title, desc, section) in enumerate(CARDS):
            col = col1 if i % 2 == 0 else col2
            with col:
                with st.container(border=True):
                    st.markdown(f"### {icon} {title}")
                    st.caption(desc)
                    if st.button("Accéder →", key=f"card_{section}", use_container_width=True):
                        st.session_state["current_section"] = section
                        st.rerun()

    else:
        # ════════════════════════════════════════════════════════════════════════
        # SECTION AGENT CASIMIR
        # ════════════════════════════════════════════════════════════════════════
        if st.session_state["current_section"] == "agent":
            st.title("🤖 Interroger l'Agent Casimir")
            st.caption(
                "Posez une question en langage naturel. **Casimir** a lu beaucoup d'articles et de comptes rendus "
                "sur **Pierrefonds**, il synthétise une réponse pour vous ! **Attention, comme chaque IA, il peut se tromper !** "
                "Vous avez accès aux sources pour vérifier. **Casimir** apprend tous les jours, mais doit se reposer de temps en temps pour regagner des crédits des fournisseurs d'IA … "
                "Vous avez quelques exemples ci-dessous. Je travaille à améliorer les réponses, à affiner les modèles d'IA."
            )
            if not base_has_pdfs:
                st.warning(
                    "**Les procès-verbaux ne sont pas indexés** dans la base actuelle. Casimir ne peut s’appuyer que sur les pages web. "
                    "Pour mettre à jour : exécutez **update_casimir.bat**, puis **deploy.bat**."
                )
            AGENT_EXAMPLES = [
                "Comment ont évolué les tarifs de la cantine scolaire ?",
                "Quels travaux de voirie ont été votés et pour quel montant ?",
                "Peux-tu résumer la restauration du château ?",
                "Comment ont travaillé les tailleurs de pierre ?",
                "Que sais-tu sur les logiciels Horizon ?",
                "Que sais-tu de Vertefeuille ?",
            ]
            ex_c1, ex_c2 = st.columns(2)
            for i, ex in enumerate(AGENT_EXAMPLES):
                with (ex_c1 if i % 2 == 0 else ex_c2):
                    if st.button(f"🔗 {ex}", key=f"agent_ex_{i}", use_container_width=True):
                        st.session_state["agent_question"] = ""
                        st.session_state["agent_auto_search"] = ex
                        st.rerun()

            agent_years = []
            n_passages  = 28

            question = st.text_area(
                "Votre question",
                placeholder="Demandez ici à Casimir!",
                height=80,
                label_visibility="collapsed",
                key="agent_question",
            )

            auto_question = st.session_state.pop("agent_auto_search", None)
            do_search = (
                st.button("Obtenir une réponse", type="primary", disabled=not question.strip(), key="agent_btn")
                or (auto_question is not None)
            )
            search_question = question.strip() if question.strip() else (auto_question or "")
            if do_search and search_question:
                allowed, remaining = rate_limit_check_and_consume()
                if not allowed:
                    st.error(QUOTA_EPUISE_MSG)
                else:
                    log_search(get_client_ip_for_log(), search_question)
                    with st.spinner("Recherche des passages pertinents…"):
                        passages = search_agent(
                            search_question, embeddings, documents, metadata,
                            n=n_passages, year_filter=agent_years, bm25=bm25,
                        )
                    if not passages:
                        st.warning("Aucun passage pertinent trouvé. Essayez d'autres mots-clés.")
                    else:
                        # Si la question porte sur Horizon mais aucun passage ne le mentionne, alerter (données manquantes)
                        if (re.search(r"\b(horizon|logiciel|logiciels)\b", search_question, re.IGNORECASE)
                                and not any(_CHUNK_HORIZON.search(doc) for doc, _, _ in passages)):
                            st.info(
                                "ℹ️ Aucun passage indexé ne mentionne les logiciels Horizon. "
                                "Pour que Casimir puisse répondre sur ce sujet, indexez les procès-verbaux : "
                                "lancez **Update_Casimir.bat** (ou `python ingest.py` sans --md-only), "
                                "puis commitez et déployez le dossier **vector_db**."
                            )
                        st.markdown("#### Réponse")
                        placeholder = st.empty()
                        full_text = ""
                        try:
                            for chunk in ask_claude_stream(search_question, passages):
                                full_text += chunk
                                placeholder.markdown(full_text + " ▌")
                            processed = _liens_sources(full_text, passages)
                            processed, noms_trouves = _lier_noms_propres(processed)
                            placeholder.markdown(processed, unsafe_allow_html=True)
                            refs = _bloc_references(processed, passages)
                            if refs:
                                st.markdown(refs)
                            # Stocker les noms pour les boutons (rendus APRÈS le bloc if/elif)
                            st.session_state["_last_noms"] = noms_trouves
                        except ValueError as e:
                            placeholder.empty()
                            st.error(str(e))
                        except Exception as e:
                            placeholder.empty()
                            st.error(f"Erreur lors de l'appel à l'API : {e}")
                        with st.expander(f"📚 {len(passages)} passages consultés"):
                            for rank, (doc, meta, score) in enumerate(passages, 1):
                                color = "green" if score > 0.6 else "orange" if score > 0.4 else "red"
                                rel_path = meta.get("rel_path", meta["filename"])
                                pdf_url = _safe_pdf_url(rel_path)
                                st.markdown(
                                    f"**#{rank}** — [{meta['filename']}]({pdf_url}) · "
                                    f"`{meta['date']}` · "
                                    f"<span style='color:{color}'>{score:.0%}</span>",
                                    unsafe_allow_html=True,
                                )
                                st.markdown(f"> {doc[:300]}{'…' if len(doc) > 300 else ''}")
            elif not question.strip():
                st.info("Saisissez une question ou cliquez sur un exemple pour lancer la recherche.")

            # Boutons « En savoir plus » — rendus HORS du bloc if do_search
            # pour que Streamlit les voit lors du rerun déclenché par le clic
            _last_noms = st.session_state.get("_last_noms")
            if _last_noms:
                st.markdown("**🔗 En savoir plus :**")
                _cols_per_row = min(len(_last_noms), 4)
                _btn_cols = st.columns(_cols_per_row)
                for _i, (_nom, _question) in enumerate(_last_noms):
                    with _btn_cols[_i % _cols_per_row]:
                        if st.button(_nom, key=f"nom_{_nom}", use_container_width=True):
                            st.session_state["agent_auto_search"] = _question
                            st.session_state["agent_question"] = ""
                            st.session_state.pop("_last_noms", None)
                            st.rerun()

        # ════════════════════════════════════════════════════════════════════════
        # SECTION RECHERCHE
        # ════════════════════════════════════════════════════════════════════════
        elif st.session_state["current_section"] == "search":
            st.title("🔍 Recherche dans la base de connaissance")
            theme_query = st.session_state.pop("_theme_query", None) or ""
            fcol1, fcol2, fcol3 = st.columns([3, 1, 1])
            with fcol1:
                year_filter = st.multiselect(
                    "Année(s)", options=list(range(2015, 2027)), default=[],
                    placeholder="Toutes les années",
                    key="search_years",
                )
            with fcol2:
                n_results = st.number_input("Nb résultats", min_value=3, max_value=50, value=15)
            with fcol3:
                exact_mode = st.toggle(
                    "Mot(s) exact(s)",
                    value=False,
                    help="Si activé, ne retourne que les passages contenant vraiment le(s) mot(s) cherché(s).",
                )

            query = st.text_input(
                "Recherche sémantique",
                value=theme_query or "",
                placeholder="Ex : Bois D'Haucourt, Vertefeuille, forêt, permis…",
                label_visibility="collapsed",
            )

            # Suggestions rapides
            cols = st.columns(len(SUGGESTIONS))
            for col, s in zip(cols, SUGGESTIONS):
                if col.button(s, key=f"s_{s}", use_container_width=True):
                    query = s

            st.divider()

            if query:
                allowed, remaining = rate_limit_check_and_consume()
                if not allowed:
                    st.error(QUOTA_EPUISE_MSG)
                else:
                    log_search(get_client_ip_for_log(), query)
                    with st.spinner("Recherche…"):
                        results = search(query, embeddings, documents, metadata,
                                        n=n_results, year_filter=year_filter, exact=exact_mode,
                                        bm25=bm25)

                    terms = [t for t in re.split(r"\s+", query) if len(t) > 2]
                    mode_label = "recherche exacte" if exact_mode else "recherche sémantique"
                    st.markdown(f"### {len(results)} résultats pour « {query} » *({mode_label})*")
                    if not results:
                        st.warning("Aucun résultat. Désactivez le mode 'Mot(s) exact(s) obligatoire' pour une recherche sémantique plus large.")
                    if year_filter:
                        st.markdown(f"*Filtrés sur : {', '.join(map(str, sorted(year_filter)))}*")

                    for rank, (doc, meta, score) in enumerate(results, 1):
                        color = "green" if score > 0.6 else "orange" if score > 0.4 else "red"
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([5, 1, 1])
                            with c1:
                                st.markdown(f"**#{rank} — {meta['filename']}**")
                                if admin:
                                    chunk_info = f"partie {meta.get('chunk', 0)+1}/{meta.get('total_chunks','?')}"
                                    st.markdown(f"Date : `{meta['date']}` · {chunk_info}")
                                else:
                                    st.markdown(f"Date : `{meta['date']}`")
                            with c2:
                                st.markdown(
                                    f"<span style='color:{color};font-size:1.3em;font-weight:bold'>"
                                    f"{score:.0%}</span>",
                                    unsafe_allow_html=True,
                                )
                            with c3:
                                rel_path = meta.get("rel_path", meta["filename"])
                                pdf_url = _safe_pdf_url(rel_path)
                                st.markdown(
                                    f'<a href="{pdf_url}" target="_blank">'
                                    f'<button style="width:100%;padding:6px;cursor:pointer;'
                                    f'border:1px solid #ccc;border-radius:4px;background:#f0f2f6;">'
                                    f'📄 Ouvrir</button></a>',
                                    unsafe_allow_html=True,
                                )
                            extract = excerpt(doc, terms)
                            st.markdown(f"> {highlight(extract, terms)}")
            else:
                st.info(
                    "Saisissez une requête ou cliquez sur une suggestion. "
                    "La recherche est **sémantique** : elle comprend le sens, pas uniquement les mots exacts."
                )

        # ════════════════════════════════════════════════════════════════════════
        # SECTION STATISTIQUES
        # ════════════════════════════════════════════════════════════════════════
        elif st.session_state["current_section"] == "stats":
            st.title("📊 Statistiques des séances du Conseil Municipal")
            stats_path = DB_DIR / "stats.json"
            if not stats_path.exists():
                st.warning("Fichier stats.json introuvable. Lancez : `python stats_extract.py`")
            else:
                stats = json.loads(stats_path.read_text(encoding="utf-8"))
            seances = [s for s in stats["seances"] if s.get("annee")]

            # ── Filtres ──────────────────────────────────────────────────────
            annees_dispo = sorted({s["annee"] for s in seances})
            sel_annees = st.multiselect(
                "Filtrer par année(s)", annees_dispo, default=[],
                placeholder="Toutes les années", key="stat_years"
            )
            if sel_annees:
                seances = [s for s in seances if s["annee"] in sel_annees]

            st.markdown(f"**{len(seances)} séances · {sum(s['nb_deliberations'] for s in seances)} délibérations**")
            st.divider()

            col1, col2 = st.columns(2)

            # ── Délibérations par année ───────────────────────────────────────
            with col1:
                par_annee = defaultdict(lambda: {"seances": 0, "delibs": 0})
                for s in seances:
                    par_annee[s["annee"]]["seances"] += 1
                    par_annee[s["annee"]]["delibs"]  += s["nb_deliberations"]
                annees = sorted(par_annee)
                fig = go.Figure()
                fig.add_bar(x=annees, y=[par_annee[a]["delibs"]  for a in annees], name="Délibérations", marker_color="#4c78a8")
                fig.add_bar(x=annees, y=[par_annee[a]["seances"] for a in annees], name="Séances",       marker_color="#f58518")
                fig.update_layout(title="Séances & délibérations par année",
                                  barmode="group", height=350, margin=dict(t=40,b=20))
                st.plotly_chart(fig, use_container_width=True)

            # ── Types de vote ─────────────────────────────────────────────────
            with col2:
                vote_counter = Counter()
                for s in seances:
                    for d in s["deliberations"]:
                        vote_counter[d["vote"]["type"]] += 1
                labels = {"unanimité": "Unanimité", "vote": "Vote avec décompte", "inconnu": "Non déterminé"}
                colors = {"unanimité": "#54a24b", "vote": "#f58518", "inconnu": "#bab0ac"}
                fig2 = px.pie(
                    names=[labels.get(k, k) for k in vote_counter],
                    values=list(vote_counter.values()),
                    color_discrete_sequence=[colors.get(k, "#aaa") for k in vote_counter],
                    title="Répartition des types de vote",
                )
                fig2.update_layout(height=350, margin=dict(t=40,b=20))
                st.plotly_chart(fig2, use_container_width=True)

            # ── Durée des séances ─────────────────────────────────────────────
            st.subheader("Durée des séances")
            seances_duree = [s for s in seances if s.get("duree_minutes")]
            if seances_duree:
                durees_all = [s["duree_minutes"] for s in seances_duree]
                m1, m2, m3 = st.columns(3)
                m1.metric("Durée moyenne", f"{sum(durees_all)/len(durees_all):.0f} min")
                m2.metric("Plus longue",   f"{max(durees_all)} min")
                m3.metric("Plus courte",   f"{min(durees_all)} min")

                col_d1, col_d2 = st.columns(2)

                # Durée moyenne par année (barres)
                with col_d1:
                    par_annee_dur = defaultdict(list)
                    for s in seances_duree:
                        if s.get("annee"):
                            par_annee_dur[s["annee"]].append(s["duree_minutes"])
                    annees_d = sorted(par_annee_dur)
                    moy_d = [sum(par_annee_dur[a]) / len(par_annee_dur[a]) for a in annees_d]
                    fig_d1 = go.Figure(go.Bar(
                        x=annees_d, y=[round(v) for v in moy_d],
                        marker_color="#4c78a8",
                        text=[f"{round(v)} min" for v in moy_d],
                        textposition="outside",
                    ))
                    fig_d1.update_layout(
                        title="Durée moyenne par année (minutes)",
                        height=350, margin=dict(t=40, b=20),
                        yaxis_title="minutes",
                    )
                    st.plotly_chart(fig_d1, use_container_width=True)

                # Durée de chaque séance (scatter)
                with col_d2:
                    dates_sc  = [s["date"] for s in seances_duree if s.get("date")]
                    durees_sc = [s["duree_minutes"] for s in seances_duree if s.get("date")]
                    labels_sc = [
                        f"{s['date']}<br>{s.get('heure_debut','?')} – {s.get('heure_fin','?')}<br>"
                        f"{s['nb_deliberations']} délibérations"
                        for s in seances_duree if s.get("date")
                    ]
                    fig_d2 = go.Figure(go.Scatter(
                        x=dates_sc, y=durees_sc,
                        mode="markers+lines",
                        marker=dict(size=8, color=durees_sc, colorscale="Blues",
                                    showscale=False),
                        line=dict(color="#aaa", width=1),
                        text=labels_sc,
                        hovertemplate="%{text}<extra></extra>",
                    ))
                    fig_d2.update_layout(
                        title="Durée de chaque séance",
                        height=350, margin=dict(t=40, b=20),
                        yaxis_title="minutes",
                        xaxis_title="",
                    )
                    st.plotly_chart(fig_d2, use_container_width=True)
            else:
                st.info("Aucune durée disponible pour la période sélectionnée.")
            st.divider()

            # ── Présence des conseillers ──────────────────────────────────────
            st.subheader("Présence des conseillers")
            presences_cpt = Counter()
            for s in seances:
                for p in s["presences"]:
                    presences_cpt[p] += 1
            # Garder les noms qui apparaissent au moins 3 fois (élus, pas agents)
            top_elus = [(nom, nb) for nom, nb in presences_cpt.most_common(25) if nb >= 3]
            if top_elus:
                noms, nbs = zip(*top_elus)
                fig3 = px.bar(
                    x=list(nbs), y=list(noms),
                    orientation="h",
                    labels={"x": "Nb séances présent", "y": ""},
                    color=list(nbs),
                    color_continuous_scale="Blues",
                    title=f"Présences sur {len(seances)} séances",
                )
                fig3.update_layout(height=max(350, len(noms) * 22),
                                   margin=dict(t=40, b=20), showlegend=False,
                                   coloraxis_showscale=False,
                                   yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig3, use_container_width=True)

            # ── Thèmes des délibérations ──────────────────────────────────────
            col3, col4 = st.columns(2)
            with col3:
                theme_cpt = Counter()
                for s in seances:
                    for d in s["deliberations"]:
                        theme_cpt[d.get("theme", "Autre")] += 1
                if theme_cpt:
                    fig4 = px.pie(
                        names=list(theme_cpt.keys()),
                        values=list(theme_cpt.values()),
                        title="Délibérations par thème",
                    )
                    fig4.update_layout(height=400, margin=dict(t=40, b=20))
                    st.plotly_chart(fig4, use_container_width=True)

            # ── Délibérations avec opposition ─────────────────────────────────
            with col4:
                opposition = []
                for s in seances:
                    for d in s["deliberations"]:
                        v = d["vote"]
                        if v["type"] == "vote" and (v.get("contre", 0) or v.get("abstentions", 0)):
                            opposition.append({
                                "date":    s["date"],
                                "titre":   d["titre"][:60],
                                "pour":    v.get("pour", 0),
                                "contre":  v.get("contre", 0),
                                "abstentions": v.get("abstentions", 0),
                                "noms_contre": ", ".join(v.get("noms_contre", [])),
                                "noms_abs":    ", ".join(v.get("noms_abstentions", [])),
                            })
                if opposition:
                    st.markdown(f"**{len(opposition)} votes avec opposition ou abstention**")
                    for o in sorted(opposition, key=lambda x: x["date"] or "", reverse=True)[:20]:
                        with st.expander(f"`{o['date']}` — {o['titre']}"):
                            st.markdown(
                                f"Pour : **{o['pour']}** · "
                                f"Contre : **{o['contre']}** ({o['noms_contre']}) · "
                                f"Abstentions : **{o['abstentions']}** ({o['noms_abs']})"
                            )
                else:
                    st.info("Aucun vote avec opposition trouvé sur la période.")

        # ════════════════════════════════════════════════════════════════════════
        # SECTION SOURCES & DOCUMENTS
        # ════════════════════════════════════════════════════════════════════════
        elif st.session_state["current_section"] == "docs":
            st.title("📄 Sources et Documents")
            st.divider()
            st.markdown("**Documents indexés** (triés par date décroissante)")
            input_dir = APP_DIR / "input"
            all_docs = sorted(input_dir.glob("*.md"), key=_pdf_date_key, reverse=True) if input_dir.exists() else []
            if all_docs:
                for p in all_docs:
                    dt = _pdf_date_key(p)
                    label_date = dt.strftime("%d/%m/%Y") if dt != datetime.min else "—"
                    # Cherche une URL source dans les premières lignes du fichier
                    source_url = None
                    try:
                        with open(p, encoding="utf-8") as f:
                            for line in f:
                                m = re.search(r'Source\s*:\s*(https?://\S+)', line)
                                if m:
                                    source_url = m.group(1)
                                    break
                    except OSError:
                        pass
                    pdf_path = PDF_DIR / (p.stem + ".pdf")
                    if source_url:
                        st.markdown(f"`{label_date}` — 🔗 [{source_url}]({source_url})")
                    elif pdf_path.exists():
                        pdf_url = _safe_pdf_url(f"{p.stem}.pdf")
                        st.markdown(f"`{label_date}` — 📄 [{p.stem}]({pdf_url})")
                    else:
                        st.markdown(f"`{label_date}` — 📝 {p.stem}")
            else:
                st.caption("Aucun document trouvé.")

        # ════════════════════════════════════════════════════════════════════════
        # SECTION ÉLECTIONS MUNICIPALES
        # ════════════════════════════════════════════════════════════════════════
        elif st.session_state["current_section"] == "elections":
            st.title("🗳️ Élections municipales")
            st.caption(
                "Cliquez sur un nom pour interroger **Casimir** sur le rôle passé de cette personne "
                "au conseil municipal de Pierrefonds (à partir des procès-verbaux indexés)."
            )
            if not listes_electorales:
                st.warning("Fichier `liste electorale.txt` introuvable ou vide.")
            else:
                cols_listes = st.columns(len(listes_electorales))
                for col_idx, (nom_liste, noms) in enumerate(listes_electorales):
                    with cols_listes[col_idx]:
                        st.markdown(f"### Liste {col_idx + 1}")
                        st.markdown(f"**{nom_liste}**")
                        # Bouton global pour toute la liste
                        if st.button(
                            f"Interroger Casimir sur les {len(noms)} candidats",
                            key=f"elec_all_{col_idx}",
                            use_container_width=True,
                            type="primary",
                        ):
                            _tous = ", ".join(noms)
                            st.session_state["agent_question"] = ""
                            st.session_state["agent_auto_search"] = (
                                f"Quels ont été les rôles respectifs de {_tous} "
                                f"au conseil municipal de Pierrefonds ? "
                                f"Adjoint, délégué, commission, désignation, nomination, vote, intervention, rapporteur."
                            )
                            st.session_state["current_section"] = "agent"
                            st.rerun()
                        st.divider()
                        for n_idx, nom in enumerate(noms):
                            if st.button(
                                f"🔗 {nom}",
                                key=f"elec_{col_idx}_{n_idx}",
                                use_container_width=True,
                            ):
                                st.session_state["agent_question"] = ""
                                st.session_state["agent_auto_search"] = (
                                    f"Quel a été le rôle de {nom} au conseil municipal de Pierrefonds ? "
                                    f"Adjoint, délégué, commission, désignation, nomination, vote, intervention, rapporteur."
                                )
                                st.session_state["current_section"] = "agent"
                                st.rerun()


if __name__ == "__main__":
    main()
