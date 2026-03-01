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
PDF_BASE_URL = "app/static"


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
RATE_LIMIT_WHITELIST = {"86.208.120.20", "90.22.160.8"}
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
    m = re.search(r'(\d{4})', name)
    if m:
        try:
            return datetime(int(m.group(1)), 1, 1)
        except ValueError:
            pass
    return datetime.min




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


@st.cache_resource(show_spinner="Chargement de la base vectorielle...")
def load_db():
    embeddings = np.load(DB_DIR / "embeddings.npy")
    with open(DB_DIR / "documents.pkl", "rb") as f:
        documents = pickle.load(f)
    with open(DB_DIR / "metadata.pkl", "rb") as f:
        metadata = pickle.load(f)
    return embeddings, documents, metadata


# ── Recherche par similarité cosinus ──────────────────────────────────────────
def search(query: str, embeddings, documents, metadata,
           n: int = 15, year_filter: list = None, exact: bool = False):
    model = load_model()
    q_emb = model.encode([query], show_progress_bar=False)[0].astype(np.float32)
    q_emb = q_emb / max(np.linalg.norm(q_emb), 1e-9)

    scores = embeddings @ q_emb  # cosine similarity (embeddings déjà normalisés)

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
                 n: int = 15, year_filter: list = None):
    """
    Combine recherche sémantique et recherche exacte filtrée sur les noms
    significatifs de la question (sans mots vides ni mots de question).
    Bonus pour les chunks contenant des chiffres quand la question porte sur tarifs/montants.
    """
    sem = search(question, embeddings, documents, metadata,
                 n=n, year_filter=year_filter, exact=False)

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
                       n=n, year_filter=year_filter, exact=True)
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
            extra = search(question, embeddings, documents, metadata, n=12, year_filter=[y], exact=False)
            for doc, meta, score in extra:
                key = (meta.get("filename", ""), meta.get("chunk", 0))
                if key not in seen:
                    seen[key] = _score_with_bonus(doc, meta, score + year_bonus[y])
        # Pour logiciels/Horizon : forcer l'inclusion de chunks 2025 contenant "logiciels" ou "renouvellement"
        if re.search(r"\b(logiciel|logiciels|horizon|renouvellement)\b", question, re.IGNORECASE):
            for kw in ("logiciels métiers", "renouvellement contrat", "Horizon"):
                extra = search(kw, embeddings, documents, metadata, n=8, year_filter=[2025, 2024], exact=True)
                for doc, meta, score in extra:
                    key = (meta.get("filename", ""), meta.get("chunk", 0))
                    if key not in seen:
                        seen[key] = _score_with_bonus(doc, meta, score + 0.12)

    # Pour voirie/travaux/montant : forcer l'inclusion de chunks qui contiennent "voirie" ou "travaux" (exact)
    if query_wants_voirie or query_wants_figures:
        for exact_query in ("voirie travaux", "voirie", "travaux"):
            exact_chunks = search(exact_query, embeddings, documents, metadata, n=10, year_filter=year_filter, exact=True)
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

    # Quand la question porte sur les montants (travaux, voirie, budget) : ajouter les chunks
    # du même PV qui mentionnent des montants (€, crédit, HT, etc.) pour que le montant voté
    # soit fourni s'il figure ailleurs dans le procès-verbal (ex. rue de l'Armistice).
    pdf_files_in_context = {
        meta.get("filename") for _, meta, _ in seen.values()
        if str(meta.get("filename", "")).lower().endswith(".pdf")
    }
    if (query_wants_figures or query_wants_voirie) and pdf_files_in_context:
        added = 0
        max_extra_amount_chunks = 12
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

    merged = sorted(seen.values(), key=lambda x: x[2], reverse=True)[:n]
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
1. Tu réponds UNIQUEMENT à partir des passages fournis entre balises <source>.
2. Si un passage ne traite pas directement du sujet de la question, ignore-le.
3. Ne cite un montant ou un chiffre QUE s'il est explicitement associé au sujet \
   exact de la question dans le passage.
4. Si l'information est absente ou insuffisante, dis-le clairement et brièvement. Ne liste jamais \
   tous les numéros de source (ex. [1, 2, 3, ... 28]) pour dire que l'info manque ; formule en une phrase.
4b. Pour les questions sur les montants (travaux de voirie, budget, délibérations) : avant de conclure \
   que les montants sont absents, cherche dans les passages tout chiffre (€, HT, TTC, euros) lié à la \
   voirie, aux travaux ou au budget ; cite-les avec leur source si tu les trouves. Si vraiment aucun \
   montant pertinent n'apparaît, indique alors où le trouver : procès-verbaux sur mairie-pierrefonds.fr \
   (vie municipale > conseil municipal). Maire-adjoint voirie : Jean-Jacques Carretero.
4c. Tarifs et barèmes : si les passages disent par exemple « les tarifs sont les suivants » ou \
   « barème selon quotient familial » mais ne contiennent pas les montants ou le tableau, \
   indique explicitement que les chiffres détaillés ne figurent pas dans les extraits fournis \
   et renvoie l'utilisateur vers la source (lien PDF ou page mairie-pierrefonds.fr) pour consulter \
   le barème complet. Les tableaux (cantine, périscolaire, etc.) sont désormais mieux indexés ; \
   si un passage contient un tableau avec des chiffres, cite-les avec leur source.
4d. Sujets récurrents (logiciels, Horizon, contrats) : tu DOIS citer le PV le plus récent (ex. 2025) \
   s'il figure dans les passages, en plus des anciens. Mentionne explicitement la décision récente \
   (ex. D2025-039, renouvellement 2025) en premier ou en complément, pour donner la situation à jour.
5. Tu réponds toujours en français, de façon concise et structurée.
6. Pour chaque affirmation, indique le numéro de la source entre crochets \
   (ex : [1], [3]) — utilise uniquement le chiffre, rien d'autre.
7. N'écris JAMAIS les balises <source> ou </source> dans ta réponse.
8. Le contexte municipal ci-dessus est fourni à titre informatif pour comprendre \
   les acronymes et les acteurs — n'en tire aucune conclusion non présente dans les sources."""


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

    user_msg = (
        f"Question : {question}\n\n"
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
            rel_path = meta.get("rel_path", fname)
            url = _safe_pdf_url(rel_path)
            icon = "📄"
        id_map[str(i)] = (fname, url, icon)
        if fname:
            fname_map[fname] = url

    def _make_link(sid):
        if sid in id_map:
            fname, url, icon = id_map[sid]
            label = fname.replace(".pdf", "").replace("[Web] ", "")
            return f"[{icon} {label}]({url})"
        return f"[{sid}]"

    # 0. Remplacer les références [N] produites par le LLM (format principal)
    #    (?!\() évite de remplacer les liens Markdown déjà formés [texte](url)
    text = re.sub(r'\[(\d+)\](?!\()', lambda m: _make_link(m.group(1)), text)

    # 1. Remplacer <source id="N" ...> résiduels (au cas où le LLM en échappe)
    text = re.sub(r'<source\s+id=["\'](\d+)["\'][^>]*>',
                  lambda m: _make_link(m.group(1)), text)

    # 2. Supprimer les balises <source> / </source> restantes
    text = re.sub(r'</source>', "", text)
    text = re.sub(r'<source[^>]*>', "", text)

    return text


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


# ── Interface principale ───────────────────────────────────────────────────────
def main():
    if "current_section" not in st.session_state:
        st.session_state["current_section"] = "home"

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
    embeddings, documents, metadata = load_db()
    # Détecter si la base contient des chunks issus de PDFs (procès-verbaux, etc.)
    def _is_pdf_meta(m: dict) -> bool:
        fn = str(m.get("filename", "")).lower()
        rp = str(m.get("rel_path", "")).lower()
        return fn.endswith(".pdf") or rp.endswith(".pdf")
    _pdf_filenames = {m.get("filename") or m.get("rel_path") for m in metadata if _is_pdf_meta(m)}
    _pdf_filenames.discard(None)
    base_has_pdfs = len(_pdf_filenames) > 0
    if admin:
        base_desc = f"**{len(documents)} passages**" + (f" (dont {len(_pdf_filenames)} fichier(s) PDF)" if base_has_pdfs else " (sites web uniquement, PDFs non indexés)")
        st.caption(f"Base indexée : {base_desc} · 🔑 Mode admin")

    # ── Bandeau supérieur (une ligne, compact) ─────────────────────────────────
    commit_date, _ = get_git_info()
    total_today = get_searches_today_count()
    remaining = rate_limit_get_remaining()
    max_display = rate_limit_get_max_for_display()
    remaining_str = "∞" if remaining is None else f"{remaining}/{max_display}"
    with st.container(border=True):
        c_nav, c_mail_deploy, c_stats = st.columns([3, 2.2, 1.4])
        with c_nav:
            nav_cols = 5 if admin else 4
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
            with btn_cols[3]:
                if st.button("🔧 Technical\u00a0Guide", key="banner_tech_guide"):
                    technical_guide()
            if admin:
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
            ("🤖", "Interroger l'Agent Casimir", "Posez une question en langage naturel. Casimir a lu beaucoup d'articles et de comptes rendus sur Pierrefonds, il synthétise une réponse pour vous ! Attention, comme chaque IA, il peut se tromper ! Vous avez accès aux sources pour vérifier. Casimir apprend tous les jours, mais doit se reposer de temps en temps pour regagner des crédits des fournisseurs d'IA …", "agent"),
            ("📊", "Statistiques des séances du Conseil Municipal", "Graphiques : délibérations par année, types de vote, durée des séances, présence des conseillers.", "stats"),
            ("🔍", "Recherche dans la base de connaissance", "Recherche sémantique dans les comptes rendus et toute la base de connaissance. Filtres par année, mode exact, suggestions.", "search"),
            ("📄", "Sources et Documents", "Liste des sources utilisées par Casimir et la recherche sémantique.", "docs"),
        ]
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
                "Posez une question en langage naturel. Casimir a lu beaucoup d'articles et de comptes rendus "
                "sur Pierrefonds, il synthétise une réponse pour vous ! Attention, comme chaque IA, il peut se tromper ! "
                "Vous avez accès aux sources pour vérifier. Casimir apprend tous les jours, mais doit se reposer de temps en temps pour regagner des crédits des fournisseurs d'IA …"
            )
            if not base_has_pdfs:
                st.warning(
                    "**Les procès-verbaux (PDF) ne sont pas indexés** dans la base actuelle. Casimir ne peut s'appuyer que sur les pages web (.md). "
                    "Pour qu'il consulte aussi les délibérations et PV : 1) exécutez **Update_Casimir.bat** et répondez **« oui »** à « Indexer aussi les PDFs ? » ; "
                    "2) **commitez et poussez le dossier vector_db** (git add vector_db/ ; git commit ; git push) ; 3) redéployez l'app sur Streamlit. Sans l’étape 2, le site en ligne garde l’ancienne base."
                )
            st.info(
                "**Tarifs et montants :** les tableaux (cantine, périscolaire, barèmes) sont maintenant extraits et indexés. Si la réponse ne donne pas les chiffres, ouvrez les **sources** proposées ci‑dessous ou consultez [mairie-pierrefonds.fr](https://www.mairie-pierrefonds.fr). L'indexation des PDFs (procès-verbaux) améliore les réponses sur les délibérations."
            )

            AGENT_EXAMPLES = [
                "Comment ont évolué les tarifs de la cantine scolaire ?",
                "Quels travaux de voirie ont été votés et pour quel montant ?",
                "Quelles délibérations concernent l'éclairage public ?",
                "Qu'a décidé le conseil sur l'intercommunalité ?",
                "Que sais-tu sur les logiciels Horizon ?",
                "Que sais-tu de Vertefeuille ?",
            ]
            st.caption("Exemples (cliquez pour lancer la recherche) :")
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
                            n=n_passages, year_filter=agent_years,
                        )
                    if not passages:
                        st.warning("Aucun passage pertinent trouvé. Essayez d'autres mots-clés.")
                    else:
                        st.markdown("#### Réponse")
                        placeholder = st.empty()
                        full_text = ""
                        try:
                            for chunk in ask_claude_stream(search_question, passages):
                                full_text += chunk
                                placeholder.markdown(full_text + " ▌")
                            placeholder.markdown(_liens_sources(full_text, passages))
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
                                        n=n_results, year_filter=year_filter, exact=exact_mode)

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
            st.markdown(
                "**Source officielle :** "
                "[mairie-pierrefonds.fr — Procès-verbaux du Conseil Municipal]"
                "(https://www.mairie-pierrefonds.fr/vie-municipale/conseil-municipal/#proces-verbal)"
            )
            st.divider()
            st.markdown("**Documents disponibles** (PV, L'ECHO, .md — triés par date décroissante)")
            static_dir = APP_DIR / "static"
            pdfs_static = list(static_dir.rglob("*.pdf")) if static_dir.exists() else []
            mds_static = list(static_dir.rglob("*.md")) if static_dir.exists() else []
            all_docs = sorted(pdfs_static + mds_static, key=_pdf_date_key, reverse=True)
            if all_docs:
                for p in all_docs:
                    dt = _pdf_date_key(p)
                    label_date = dt.strftime("%d/%m/%Y") if dt != datetime.min else "—"
                    rel_path = str(p.relative_to(static_dir)).replace("\\", "/")
                    doc_url = _safe_pdf_url(rel_path)
                    icon = "📄" if p.suffix.lower() == ".pdf" else "📝"
                    st.markdown(
                        f"`{label_date}` — [{icon} {p.name}]({doc_url})",
                    )
            else:
                st.caption("Aucun document trouvé.")


if __name__ == "__main__":
    main()
