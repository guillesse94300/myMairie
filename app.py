"""
app.py — Interface Streamlit de recherche dans les comptes rendus
Usage  : streamlit run app.py
"""

import re
import pickle
import subprocess
import numpy as np
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from sentence_transformers import SentenceTransformer
from pathlib import Path

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
    "Compiègne",
    "permis de construire",
    "urbanisme",
    "taxe foncière",
    "voirie",
    "eau potable",
    "Le Rocher",
    "Fontaine",
]

THEMES = {
    "📜 Convention / Contrat":  "convention contrat accord partenariat prestataire signature",
    "💶 Budget / Finances":     "budget subvention investissement dépenses recettes dotation emprunt",
    "👷 Emploi / RH":           "emploi recrutement agent personnel rémunération poste vacataire",
    "💰 Tarifs / Redevances":   "tarif redevance barème taux prix cotisation",
    "🏫 École / Scolaire":      "école scolaire enseignement élèves périscolaire cantine ATSEM classe",
    "🚧 Travaux / Voirie":      "travaux voirie chaussée route réfection rénovation chemin",
    "⚡ Énergie / Éclairage":   "énergie électricité éclairage SIED photovoltaïque compteur",
    "🌲 Forêt / Bois":          "forêt boisement Bois D'Haucourt Vertefeuille sylviculture coupe",
    "🏗️ Urbanisme / Permis":    "permis de construire PLU urbanisme zonage lotissement bâtiment",
    "🧒 Enfance / Jeunesse":    "enfants jeunesse loisirs accueil centre de loisirs ALSH",
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
        [data-testid='stSidebar'] > div:first-child { padding-top: 0 !important; }
        [data-testid='stSidebarContent'] { padding-top: 0 !important; }
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
            'footer'
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

    # ── Filtres en ligne ─────────────────────────────────────────────────────────
    fcol1, fcol2, fcol3 = st.columns([3, 1, 1])
    with fcol1:
        year_filter = st.multiselect(
            "Année(s)", options=list(range(2015, 2027)), default=[],
            placeholder="Toutes les années",
        )
    with fcol2:
        n_results = st.number_input("Nb résultats", min_value=3, max_value=50, value=15)
    with fcol3:
        exact_mode = st.toggle(
            "Mot(s) exact(s)",
            value=False,
            help="Si activé, ne retourne que les passages contenant vraiment le(s) mot(s) cherché(s).",
        )

    if not DB_DIR.exists():
        st.error("Base vectorielle introuvable. Lancez d'abord : `python ingest.py`")
        st.stop()

    admin = is_admin()
    embeddings, documents, metadata = load_db()
    if admin:
        st.caption(f"Base indexée : **{len(documents)} passages** issus des PDFs · 🔑 Mode admin")

    # ── Sidebar ─────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("**Thèmes**")
        theme_query = None
        for label, tq in THEMES.items():
            if st.button(label, use_container_width=True):
                theme_query = tq
        st.markdown("---")
        st.markdown("**Lien Direct**")
        pdfs = sorted(PDF_DIR.glob("*.pdf"), key=_pdf_date_key, reverse=True)
        if pdfs:
            links = "".join(
                f'<a href="{PDF_BASE_URL}/{p.name}" target="_blank" '
                f'style="display:block;font-size:0.78em;margin:3px 0;'
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
                f'color:#1a73e8;text-decoration:none;" '
                f'title="{p.name}">📄 {p.name}</a>'
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

    # ── Barre de recherche ───────────────────────────────────────────────────────
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

    # ── Résultats ────────────────────────────────────────────────────────────────
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
            pdf_path = PDF_DIR / meta["filename"]
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


if __name__ == "__main__":
    main()
