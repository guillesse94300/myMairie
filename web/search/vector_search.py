# -*- coding: utf-8 -*-
"""Charge la base vectorielle et exécute les requêtes (singleton au premier appel)."""
import re
import json
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

from django.conf import settings

STORE_DIR = getattr(settings, "BASE_VECTORIELLE", Path(__file__).resolve().parent.parent.parent / "base_vectorielle")
EMBEDDINGS_FILE = Path(STORE_DIR) / "embeddings.npz"
META_FILE = Path(STORE_DIR) / "metadata.json"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
N_RESULTS_DEFAULT = 12
# Seuil de similarité minimal : les résultats en dessous sont exclus (réduit les faux positifs).
MIN_SIMILARITY = 0.55
# Si le document contient le(s) mot(s) de la requête, accepter à partir de ce seuil (les scores sémantiques pour un seul mot sont souvent bas).
MIN_SIMILARITY_IF_KEYWORD_MATCH = 0.15
# Pour les requêtes courtes (≤ N mots), exiger que le texte contienne au moins un des mots.
KEYWORD_FILTER_MAX_WORDS = 3

_model = None
_embeddings = None
_documents = None
_metadatas = None


def _cosine_similarity(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)


def _query_words(query: str):
    """Retourne la liste des mots significatifs de la requête (≥ 2 caractères)."""
    words = re.findall(r"[a-zA-ZÀ-ÿ\u00C0-\u017F]+", query.strip())
    return [w for w in words if len(w) >= 2]


def _text_contains_any_word(text: str, words: list) -> bool:
    """Vrai si le texte contient au moins un des mots (insensible à la casse)."""
    if not text or not words:
        return True
    lower = text.lower()
    return any(w.lower() in lower for w in words)


def _load():
    global _model, _embeddings, _documents, _metadatas
    if _embeddings is not None:
        return
    if not EMBEDDINGS_FILE.exists() or not META_FILE.exists():
        raise FileNotFoundError("Base vectorielle absente. Exécutez build_vector_store.py.")
    _model = SentenceTransformer(EMBEDDING_MODEL)
    data = np.load(EMBEDDINGS_FILE)
    _embeddings = data["embeddings"]
    with open(META_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    _documents = meta["documents"]
    _metadatas = meta["metadatas"]


def search(query: str, n: int = N_RESULTS_DEFAULT):
    """
    Retourne une liste de {text, meta, distance, similarity}.
    - Seuil de similarité : résultats avec similarity < MIN_SIMILARITY exclus.
    - Pour requêtes courtes : le document doit contenir au moins un mot de la requête.
      Dans ce cas, on parcourt tous les passages contenant le mot (pas seulement le top par similarité).
    """
    _load()
    q_emb = _model.encode([query], convert_to_numpy=True)[0]
    scores = np.array([_cosine_similarity(q_emb, e) for e in _embeddings])
    words = _query_words(query)
    use_keyword_filter = len(words) <= KEYWORD_FILTER_MAX_WORDS and len(words) >= 1

    if use_keyword_filter:
        # Trouver TOUS les passages contenant au moins un mot de la requête, puis trier par similarité.
        indices_with_word = [
            i for i in range(len(_documents))
            if _text_contains_any_word(_documents[i], words)
        ]
        # Garder ceux au-dessus du seuil, trier par score décroissant, prendre n.
        candidates = [
            (i, float(scores[i]))
            for i in indices_with_word
            if scores[i] >= MIN_SIMILARITY_IF_KEYWORD_MATCH
        ]
        candidates.sort(key=lambda x: -x[1])
        idx = [i for i, _ in candidates[:n]]
    else:
        idx = np.argsort(-scores)[:n]
        idx = [i for i in idx if scores[i] >= MIN_SIMILARITY]

    results = []
    for i in idx:
        sim = float(scores[i])
        results.append({
            "text": _documents[i],
            "meta": _metadatas[i],
            "distance": float(1 - sim),
            "similarity": round(sim, 4),
        })
    return results


def is_available():
    return EMBEDDINGS_FILE.exists() and META_FILE.exists()
