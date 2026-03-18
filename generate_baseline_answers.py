"""
generate_baseline_answers.py
----------------------------

Script utilitaire pour calculer les réponses complètes de Casimir
sur les questions d'exemple de l'agent, et les enregistrer comme
baseline dans `tests/baseline_agent_examples.json`.

Usage (dans le venv du projet) :

    python generate_baseline_answers.py

Prérequis :
- Base vectorielle présente (`python ingest.py` déjà exécuté)
- Package `groq` installé
- Clé API configurée dans `.streamlit/secrets.toml` (`GROQ_API_KEY`)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import app


BASELINE_PATH = Path(__file__).parent / "tests" / "baseline_agent_examples.json"

QUESTIONS = [
    "Comment ont évolué les tarifs de la cantine scolaire ?",
    "Quels travaux de voirie ont été votés et pour quel montant ?",
    "Quelles délibérations concernent l'éclairage public ?",
    "Qu'a décidé le conseil sur l'intercommunalité ?",
    "Que sais-tu sur les logiciels Horizon ?",
    "Que sais-tu de Vertefeuille ?",
]


def _collect_answer(question: str) -> str:
    """Exécute la partie RAG+LLM d'app.py pour une question et renvoie la réponse complète."""
    embeddings, documents, metadata, _bm25 = app.load_db()
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    if not passages:
        raise RuntimeError(f"Aucun passage trouvé pour la question : {question!r}")

    chunks = []
    for piece in app.ask_claude_stream(question, passages):
        chunks.append(piece)
    full_text = "".join(chunks)
    # On applique le même post-traitement que dans l'UI (liens de sources + bloc Références)
    processed = app._liens_sources(full_text, passages)
    refs = app._bloc_references(processed, passages)
    if refs:
        processed = processed.rstrip() + "\n\n" + refs + "\n"
    return processed.strip()


def main() -> None:
    print("Génération des réponses baseline pour Casimir…")
    baselines: dict[str, str] = {}
    for idx, q in enumerate(QUESTIONS, start=1):
        print(f"- Question : {q}")
        answer = _collect_answer(q)
        baselines[q] = answer
        print(f"  -> {len(answer)} caracteres")
        # Espace de 5 secondes entre deux appels à Casimir pour éviter de saturer l'API.
        if idx < len(QUESTIONS):
            print("  (pause 5 secondes avant la prochaine question…)")
            time.sleep(5)

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(baselines, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBaseline enregistrée dans : {BASELINE_PATH}")


if __name__ == "__main__":
    main()

