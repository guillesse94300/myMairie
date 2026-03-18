import json
from difflib import SequenceMatcher
from pathlib import Path

import pytest

import app


VECTOR_DB_FILES = [
    app.DB_DIR / "embeddings.npy",
    app.DB_DIR / "documents.pkl",
    app.DB_DIR / "metadata.pkl",
]

VECTOR_DB_PRESENT = all(p.exists() for p in VECTOR_DB_FILES)

requires_vector_db = pytest.mark.skipif(
    not VECTOR_DB_PRESENT,
    reason="Base vectorielle absente. Lancez d'abord `python ingest.py` pour générer vector_db/.",
)

BASELINE_PATH = Path(__file__).parent / "baseline_agent_examples.json"

AGENT_EXAMPLE_QUESTIONS = [
    "Comment ont évolué les tarifs de la cantine scolaire ?",
    "Quels travaux de voirie ont été votés et pour quel montant ?",
    "Quelles délibérations concernent l'éclairage public ?",
    "Qu'a décidé le conseil sur l'intercommunalité ?",
    "Que sais-tu sur les logiciels Horizon ?",
    "Que sais-tu de Vertefeuille ?",
]


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(k.lower() in lower for k in keywords)


@pytest.fixture(scope="session")
def loaded_db():
    """Charge en une fois la base vectorielle pour l'ensemble de la session de tests."""
    if not VECTOR_DB_PRESENT:
        pytest.skip("Base vectorielle absente. Lancez d'abord `python ingest.py` pour générer vector_db/.")
    embeddings, documents, metadata, _bm25 = app.load_db()
    return embeddings, documents, metadata


def _sequence_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@pytest.mark.skipif(
    not BASELINE_PATH.exists(),
    reason="Baseline absente. Exécutez `python generate_baseline_answers.py` pour la créer.",
)
@requires_vector_db
@pytest.mark.parametrize("question", AGENT_EXAMPLE_QUESTIONS)
def test_agent_answer_close_to_baseline(question: str, loaded_db):
    """
    Compare la réponse actuelle de Casimir à la baseline pour chaque question exemple.

    Cela garantit que le comportement global de l'agent ne change pas brutalement
    (contenu trop différent) tout en laissant un peu de marge aux variations mineures.
    """
    embeddings, documents, metadata = loaded_db
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    assert passages, f"Aucun passage trouvé pour la question : {question}"

    raw_chunks = []
    for piece in app.ask_claude_stream(question, passages):
        raw_chunks.append(piece)
    current_answer = "".join(raw_chunks)
    current_answer = current_answer.strip()

    baselines = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline_answer = baselines.get(question, "").strip()
    assert baseline_answer, f"Aucune baseline enregistrée pour la question : {question}"

    sim = _sequence_similarity(current_answer, baseline_answer)
    len_current = len(current_answer)
    len_baseline = len(baseline_answer)
    ratio = len_current / max(len_baseline, 1)

    # On ne cherche pas à figer mot à mot la réponse (le modèle reste stochastique),
    # mais à détecter uniquement les écarts grossiers : réponse vide, dix fois plus
    # courte ou plus longue que la baseline, etc.
    assert len_current > 0, f"Réponse vide pour la question : {question!r}"
    assert 0.4 <= ratio <= 2.5, (
        f"Longueur de réponse trop différente de la baseline pour : {question!r} "
        f"(ratio {ratio:.2f}, len actuelle {len_current}, baseline {len_baseline})"
    )
    # Seuil de similarité très bas : on accepte de grandes reformulations, on veut juste
    # éviter les réponses complètement hors sujet.
    assert sim >= 0.30, (
        f"Réponse très différente de la baseline pour : {question!r} "
        f"(similarité {sim:.2f} < 0.30)"
    )


@requires_vector_db
@pytest.mark.parametrize("question", AGENT_EXAMPLE_QUESTIONS)
def test_all_example_questions_return_results(question: str, loaded_db):
    """Chaque question suggérée doit renvoyer des passages pertinents."""
    embeddings, documents, metadata = loaded_db
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    assert passages, f"Aucun passage trouvé pour la question : {question}"
    assert len(passages) >= 5, f"Trop peu de passages pour : {question!r}"


@requires_vector_db
def test_cantine_question_returns_tarif_chunks(loaded_db):
    """Pour la cantine, Casimir doit voir des passages avec 'cantine' et des montants."""
    embeddings, documents, metadata = loaded_db
    question = "Comment ont évolué les tarifs de la cantine scolaire ?"
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    matches = [
        (doc, meta, score)
        for doc, meta, score in passages
        if _contains_any(doc, ["cantine", "restauration scolaire"])
        and _has_digit(doc)
    ]
    assert matches, "Aucun passage ne contient à la fois 'cantine' et des montants chiffrés."


@requires_vector_db
def test_voirie_question_returns_works_with_amounts(loaded_db):
    """Pour la voirie, Casimir doit trouver des travaux avec des montants."""
    embeddings, documents, metadata = loaded_db
    question = "Quels travaux de voirie ont été votés et pour quel montant ?"
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    matches = [
        (doc, meta, score)
        for doc, meta, score in passages
        if app._CHUNK_VOIRIE.search(doc) and app._CHUNK_HAS_NUMBER.search(doc)
    ]
    assert matches, (
        "Aucun passage ne combine des mentions de voirie/travaux et des montants. "
        "Les heuristiques de recherche pour les travaux de voirie semblent dégradées."
    )


@requires_vector_db
def test_eclairage_public_question_returns_relevant_deliberations(loaded_db):
    """Pour l'éclairage public, au moins un passage doit clairement concerner ce sujet."""
    embeddings, documents, metadata = loaded_db
    question = "Quelles délibérations concernent l'éclairage public ?"
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    keywords = ["éclairage", "eclairage", "SE60", "SIED", "énergie", "eclairage public"]
    matches = [
        (doc, meta, score)
        for doc, meta, score in passages
        if _contains_any(doc, keywords)
    ]
    assert matches, "Aucun passage trouvé sur l'éclairage public ou les syndicats d'énergie (SE60 / SIED)."


@requires_vector_db
def test_intercommunalite_question_returns_intercommunal_passages(loaded_db):
    """Pour l'intercommunalité, vérifier que des organismes intercommunaux apparaissent."""
    embeddings, documents, metadata = loaded_db
    question = "Qu'a décidé le conseil sur l'intercommunalité ?"
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    keywords = [
        "intercommunalité",
        "intercommunalite",
        "CCLoise",
        "communauté de communes",
        "communauté d'agglomération",
        "SMOA",
        "SIVOC",
        "SMIOCCE",
    ]
    matches = [
        (doc, meta, score)
        for doc, meta, score in passages
        if _contains_any(doc, keywords)
    ]
    assert matches, "Aucun passage ne mentionne clairement l'intercommunalité ou les syndicats intercommunaux."


@requires_vector_db
def test_horizon_question_prioritises_horizon_chunks(loaded_db):
    """Pour Horizon, Casimir doit obtenir au moins un passage parlant des logiciels Horizon."""
    embeddings, documents, metadata = loaded_db
    question = "Que sais-tu sur les logiciels Horizon ?"
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    horizon_chunks = [
        (doc, meta, score)
        for doc, meta, score in passages
        if app._CHUNK_HORIZON.search(doc)
    ]
    assert horizon_chunks, (
        "Aucun passage de la réponse RAG ne mentionne Horizon ou les logiciels métiers, "
        "alors que la question porte explicitement sur ce sujet."
    )


@requires_vector_db
def test_vertefeuille_question_returns_forest_passages(loaded_db):
    """Pour Vertefeuille, vérifier que des passages mentionnent clairement ce massif forestier."""
    embeddings, documents, metadata = loaded_db
    question = "Que sais-tu de Vertefeuille ?"
    passages = app.search_agent(
        question,
        embeddings,
        documents,
        metadata,
        n=28,
        year_filter=None,
    )
    matches = [
        (doc, meta, score)
        for doc, meta, score in passages
        if _contains_any(doc, ["vertefeuille", "vertefeuilles"])
    ]
    assert matches, "Aucun passage trouvé qui mentionne clairement Vertefeuille."

