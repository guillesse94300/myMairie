"""
app.py — Interface Streamlit de recherche dans les comptes rendus
Usage  : streamlit run app.py
"""

import re
import json
import pickle
import subprocess
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from collections import Counter, defaultdict
from sentence_transformers import SentenceTransformer
from pathlib import Path

try:
    from groq import Groq as _Groq
    _GROQ_OK = True
except ImportError:
    _GROQ_OK = False

# ── Configuration ──────────────────────────────────────────────────────────────
APP_DIR  = Path(__file__).parent
PDF_DIR  = APP_DIR / "static"          # PDFs servis par Streamlit static serving
DB_DIR   = APP_DIR / "vector_db"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# URL de base pour les PDFs (fonctionne local ET sur Streamlit Cloud)
PDF_BASE_URL = "app/static"

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
@st.cache_data(show_spinner=False)
def get_git_info():
    cwd = str(APP_DIR)
    try:
        commit_date = subprocess.check_output(
            ["git", "log", "-1", "--format=%ci"],
            cwd=cwd, stderr=subprocess.DEVNULL
        ).decode().strip()[:16]   # "YYYY-MM-DD HH:MM"
        commit_date = commit_date.replace("T", " ")
    except Exception:
        commit_date = "—"
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
    """
    sem = search(question, embeddings, documents, metadata,
                 n=n, year_filter=year_filter, exact=False)

    # Extraire uniquement les mots porteurs de sens (≥ 4 chars, hors stop words)
    raw = [t.strip("'\".,?!") for t in re.split(r'\W+', question)]
    sig = [t for t in raw
           if len(t) >= 4
           and t.lower().replace('é','e').replace('è','e')
                        .replace('ê','e').replace('û','u') not in _STOP_FR]

    seen: dict = {}
    if sig:
        focused = " ".join(sig)
        exact = search(focused, embeddings, documents, metadata,
                       n=n, year_filter=year_filter, exact=True)
        for doc, meta, score in exact:
            key = (meta.get("filename", ""), meta.get("chunk", 0))
            seen[key] = (doc, meta, score + 0.05)   # bonus priorité

    for doc, meta, score in sem:
        key = (meta.get("filename", ""), meta.get("chunk", 0))
        if key not in seen:
            seen[key] = (doc, meta, score)

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

## Règles strictes
1. Tu réponds UNIQUEMENT à partir des passages fournis entre balises <source>.
2. Si un passage ne traite pas directement du sujet de la question, ignore-le.
3. Ne cite un montant ou un chiffre QUE s'il est explicitement associé au sujet \
   exact de la question dans le passage.
4. Si l'information est absente ou insuffisante, dis-le clairement et brièvement.
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
    # Mapping id (1-based) → (filename, url)
    id_map = {}
    fname_map = {}
    for i, (_, meta, _) in enumerate(passages, 1):
        fname = meta.get("filename", "")
        url   = f"{PDF_BASE_URL}/{fname}"
        id_map[str(i)] = (fname, url)
        if fname:
            fname_map[fname] = url

    def _make_link(sid):
        if sid in id_map:
            fname, url = id_map[sid]
            label = fname.replace(".pdf", "")
            return f"[📄 {label}]({url})"
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


# ── Interface principale ───────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Procès-verbaux — Pierrefonds",
        page_icon="🏛️",
        layout="wide",
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
        </style>""",
        unsafe_allow_html=True,
    )
    # Masquage dynamique via JS (Streamlit Cloud injecte le bouton après le rendu)
    components.html("""
    <script>
    const hide = () => {
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
        sel.forEach(s => {
            window.parent.document.querySelectorAll(s)
                .forEach(el => { el.style.display = 'none'; });
        });
    };
    hide();
    new MutationObserver(hide).observe(
        window.parent.document.body,
        { childList: true, subtree: true }
    );
    </script>
    """, height=0)

    st.title("🏛️ Procès-verbaux de séances - Conseil Municipal Pierrefonds")
    st.caption("Source : https://www.mairie-pierrefonds.fr/vie-municipale/conseil-municipal/#proces-verbal")

    if not DB_DIR.exists():
        st.error("Base vectorielle introuvable. Lancez d'abord : `python ingest.py`")
        st.stop()

    admin = is_admin()
    embeddings, documents, metadata = load_db()
    if admin:
        st.caption(f"Base indexée : **{len(documents)} passages** issus des PDFs · 🔑 Mode admin")

    # ── Sidebar ─────────────────────────────────────────────────────────────────
    with st.sidebar:
        components.html("""
        <style>
          body { margin:0; padding:0; background:transparent;
                 font-family:"Source Sans Pro","Segoe UI",sans-serif; }
          #ip  { font-size:0.75em; color:#888; margin:0; padding:0; }
        </style>
        <p id="ip">🌐 Détection…</p>
        <script>
        (function() {
            var el = document.getElementById('ip');
            Promise.race([
                fetch('https://api.ipify.org?format=json').then(r => r.json()).then(d => d.ip),
                fetch('https://icanhazip.com/').then(r => r.text()).then(t => t.trim()),
                fetch('https://checkip.amazonaws.com/').then(r => r.text()).then(t => t.trim())
            ])
            .then(function(ip){ el.textContent = '🌐 ' + ip.replace(/\s/g,''); })
            .catch(function(){  el.textContent = '🌐 —'; });
        })();
        </script>
        """, height=22)
        st.markdown('<p style="font-weight:600;margin:0 0 0.4rem 0;padding:0">Thèmes</p>', unsafe_allow_html=True)
        theme_query = None
        for label, tq in THEMES.items():
            if st.button(label, use_container_width=True):
                theme_query = tq
                st.session_state["_switch_to_search"] = True
        st.markdown("---")
        st.markdown("**Lien Direct**")
        pdfs = sorted(PDF_DIR.glob("*.pdf"), key=_pdf_date_key, reverse=True)
        if pdfs:
            def _fmt_label(p):
                dt = _pdf_date_key(p)
                if dt == datetime.min:
                    return p.stem
                return dt.strftime("%d/%m/%Y")
            links = "".join(
                f'<a href="{PDF_BASE_URL}/{p.name}" target="_blank" '
                f'style="display:block;font-size:0.78em;margin:3px 0;'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
                f'color:#1a73e8;text-decoration:none;" '
                f'title="{p.name}">📄 {_fmt_label(p)}</a>'
                for p in pdfs
            )
            st.markdown(
                f'<div style="max-height:300px;overflow-y:auto;'
                f'border:1px solid #e0e0e0;border-radius:6px;padding:6px 10px;">'
                f'{links}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("Aucun PDF trouvé.")
        st.markdown("---")
        commit_date, version = get_git_info()
        st.markdown(
            f"<div style='font-size:0.78em;color:#888;line-height:1.6'>"
            f"🏷️ Version&nbsp;&nbsp;<b>{version}</b><br>"
            f"🕐 Commit&nbsp;&nbsp;<b>{commit_date}</b>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Onglets ─────────────────────────────────────────────────────────────────
    tab_search, tab_stats, tab_agent = st.tabs(["🔍 Recherche", "📊 Statistiques", "🤖 Agent Q&R"])

    # Bascule automatique vers l'onglet Recherche quand un thème est cliqué
    if st.session_state.get("_switch_to_search", False):
        st.session_state["_switch_to_search"] = False
        components.html("""
        <script>
        setTimeout(function () {
            var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
            if (tabs && tabs[0]) tabs[0].click();
        }, 150);
        </script>
        """, height=0)

    # ════════════════════════════════════════════════════════════════════════════
    # ONGLET RECHERCHE
    # ════════════════════════════════════════════════════════════════════════════
    with tab_search:
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
                        pdf_url = f"{PDF_BASE_URL}/{meta['filename']}"
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

    # ════════════════════════════════════════════════════════════════════════════
    # ONGLET STATISTIQUES
    # ════════════════════════════════════════════════════════════════════════════
    with tab_stats:
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

    # ════════════════════════════════════════════════════════════════════════════
    # ONGLET AGENT Q&R
    # ════════════════════════════════════════════════════════════════════════════
    with tab_agent:
        st.markdown(
            "Posez une question en langage naturel. L'agent recherche les passages "
            "pertinents dans les PV puis génère une réponse synthétisée."
        )
        st.caption(
            "Exemples : *Quelles décisions ont été prises sur le Bois d'Haucourt ?* · "
            "*Comment ont évolué les tarifs de la cantine scolaire (Louis Lesueur) ?* · "
            "*Quels travaux de voirie ont été votés et pour quel montant ?* · "
            "*Quelles délibérations concernent le SE60 ou l'éclairage public ?* · "
            "*Qu'a décidé le conseil sur l'intercommunalité avec la CCLoise ?* · "
            "*Que sais-tu sur les logiciels Horizon ?*"
        )

        agent_years = []
        n_passages = 15

        question = st.text_area(
            "Votre question",
            placeholder="Ex : Pourquoi la fontaine est cassée ?",
            height=80,
            label_visibility="collapsed",
        )

        if st.button("Obtenir une réponse", type="primary", disabled=not question.strip()):
            with st.spinner("Recherche des passages pertinents…"):
                passages = search_agent(
                    question, embeddings, documents, metadata,
                    n=n_passages, year_filter=agent_years,
                )

            if not passages:
                st.warning("Aucun passage pertinent trouvé. Essayez d'autres mots-clés.")
            else:
                st.markdown("#### Réponse")
                placeholder = st.empty()
                full_text = ""
                try:
                    for chunk in ask_claude_stream(question, passages):
                        full_text += chunk
                        placeholder.markdown(full_text + " ▌")
                    # Post-traitement : balises → liens PDF
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
                        pdf_url = f"{PDF_BASE_URL}/{meta['filename']}"
                        st.markdown(
                            f"**#{rank}** — [{meta['filename']}]({pdf_url}) · "
                            f"`{meta['date']}` · "
                            f"<span style='color:{color}'>{score:.0%}</span>",
                            unsafe_allow_html=True,
                        )
                        st.markdown(f"> {doc[:300]}{'…' if len(doc) > 300 else ''}")
        elif not question.strip():
            st.info("Saisissez une question ci-dessus puis cliquez sur **Obtenir une réponse**.")


if __name__ == "__main__":
    main()
