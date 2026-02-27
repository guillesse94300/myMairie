"""
app.py — Interface Streamlit de recherche dans les comptes rendus
Usage  : streamlit run app.py
"""

import re
import pickle
import subprocess
import numpy as np
import streamlit as st
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
    "forêt",
    "permis de construire",
    "urbanisme",
    "taxe foncière",
    "voirie",
    "eau potable",
    "budget",
    "école",
]

THEMES = {
    "🌲 Forêt / Bois":          "Bois D'Haucourt Vertefeuille forêt boisement",
    "🏗️ Urbanisme":             "permis de construire PLU zonage urbanisme",
    "💶 Budget / Taxes":        "budget taxe foncière dotation subvention",
    "🚧 Voirie":                "voirie route chemin travaux",
    "💧 Eau / Assainissement":  "eau potable assainissement réseau",
    "🏫 École":                 "école enseignement enfants périscolaire",
}


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
        page_title="Comptes Rendus — Pierrefonds",
        page_icon="🏛️",
        layout="wide",
    )

    st.title("🏛️ Comptes Rendus du Conseil Municipal — Pierrefonds")

    if not DB_DIR.exists():
        st.error("Base vectorielle introuvable. Lancez d'abord : `python ingest.py`")
        st.stop()

    embeddings, documents, metadata = load_db()
    st.caption(f"Base indexée : **{len(documents)} passages** issus des PDFs")

    # ── Sidebar ─────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Filtres")
        year_filter = st.multiselect(
            "Année(s)", options=list(range(2015, 2027)), default=[],
            placeholder="Toutes les années",
        )
        n_results = st.number_input("Nb résultats", min_value=3, max_value=50, value=15)
        exact_mode = st.toggle(
            "Mot(s) exact(s) obligatoire",
            value=False,
            help="Si activé, ne retourne que les passages contenant vraiment le(s) mot(s) cherché(s).",
        )
        st.markdown("---")
        st.markdown("**Thèmes**")
        theme_query = None
        for label, tq in THEMES.items():
            if st.button(label, use_container_width=True):
                theme_query = tq
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
                    chunk_info = f"partie {meta.get('chunk', 0)+1}/{meta.get('total_chunks','?')}"
                    st.markdown(f"Date : `{meta['date']}` · {chunk_info}")
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
