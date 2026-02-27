# -*- coding: utf-8 -*-
"""
Interroge la base vectorielle par similarité sémantique.
Usage: python query_vector_store.py "votre question"
       python query_vector_store.py   (mode interactif)
Applique le même seuil de similarité et filtre « mot présent » que l’appli web.
"""
import re
import sys
import json
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

DOSSIER = Path(__file__).resolve().parent
STORE_DIR = DOSSIER / "base_vectorielle"
EMBEDDINGS_FILE = STORE_DIR / "embeddings.npz"
META_FILE = STORE_DIR / "metadata.json"
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
N_RESULTS = 8
MIN_SIMILARITY = 0.55
MIN_SIMILARITY_IF_KEYWORD_MATCH = 0.15
KEYWORD_FILTER_MAX_WORDS = 3


def cosine_similarity(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)


def query_words(question):
    words = re.findall(r"[a-zA-ZÀ-ÿ\u00C0-\u017F]+", question.strip())
    return [w for w in words if len(w) >= 2]


def text_contains_any_word(text, words):
    if not text or not words:
        return True
    lower = text.lower()
    return any(w.lower() in lower for w in words)


def main():
    if not STORE_DIR.exists() or not EMBEDDINGS_FILE.exists() or not META_FILE.exists():
        print("La base vectorielle n'existe pas. Exécutez d'abord : python build_vector_store.py")
        sys.exit(1)

    print("Chargement du modèle et de la base...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    data = np.load(EMBEDDINGS_FILE)
    embeddings = data["embeddings"]
    with open(META_FILE, "r", encoding="utf-8") as f:
        meta = json.load(f)
    documents = meta["documents"]
    metadatas = meta["metadatas"]

    def requete(question, n=N_RESULTS):
        q_emb = model.encode([question], convert_to_numpy=True)[0]
        scores = np.array([cosine_similarity(q_emb, e) for e in embeddings])
        words = query_words(question)
        use_keyword_filter = len(words) <= KEYWORD_FILTER_MAX_WORDS and len(words) >= 1
        if use_keyword_filter:
            indices_with_word = [
                i for i in range(len(documents))
                if text_contains_any_word(documents[i], words)
            ]
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
        return [(documents[i], metadatas[i], float(1 - scores[i]), float(scores[i])) for i in idx]

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"\nRecherche : « {question} »\n")
        results = requete(question)
    else:
        print("Mode interactif. Entrez une question (ou vide pour quitter).\n")
        question = input("Question > ").strip()
        if not question:
            return
        results = requete(question)

    if not results:
        print("Aucun résultat.")
        return

    def safe_print(s):
        try:
            print(s)
        except UnicodeEncodeError:
            print(s.encode("cp1252", errors="replace").decode("cp1252"))

    for i, (doc, meta, dist, sim) in enumerate(results, 1):
        safe_print(f"--- Résultat {i} (pertinence {sim:.2f}) | {meta.get('source', '')} ---")
        safe_print(doc[:500] + ("..." if len(doc) > 500 else ""))
        print()

    if len(sys.argv) > 1:
        return

    while True:
        try:
            question = input("Question > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        results = requete(question)
        if not results:
            print("Aucun résultat.\n")
            continue
        for i, (doc, meta, dist, sim) in enumerate(results, 1):
            safe_print(f"--- Résultat {i} (pertinence {sim:.2f}) | {meta.get('source', '')} ---")
            safe_print(doc[:500] + ("..." if len(doc) > 500 else ""))
            print()


if __name__ == "__main__":
    main()
