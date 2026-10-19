"""La récupération est testée SANS LLM : uniquement embeddings + Chroma."""

import pytest

from app.embeddings import HashEmbeddings, tokenize
from app.rag import retrieve


@pytest.mark.parametrize(
    "question, expected_doc",
    [
        ("Quelle procédure pour un incident service_flood ?", "runbook-service-flood.md"),
        ("Que faire en cas de saturation, le ratio 5xx explose sur payment-api", "runbook-service-flood.md"),
        ("Comment restaurer le dump Postgres après une corruption ?", "runbook-data-corruption.md"),
        ("Quels sont le RPO et le RTO ?", "runbook-data-corruption.md"),
        ("Quelles actions la table de décision applique-t-elle pour auth_abuse ?", "decision_table.yml"),
        ("Que s'est-il passé pour l'incident inc-0002 ?", "journal/inc-0002"),
        ("Quels ports sont exposés, quel composant est le seul exposé ?", "architecture.md"),
    ],
)
def test_retrieval_returns_the_right_passage(indexed, question, expected_doc):
    _, store = indexed
    passages = retrieve(store, question, k=3)
    assert passages, "aucun passage renvoyé"
    assert passages[0].doc == expected_doc, [(p.doc, round(p.score, 2)) for p in passages]


def test_incident_journal_is_retrievable_as_incident_kind(indexed):
    _, store = indexed
    top = retrieve(store, "Combien de temps a duré la remédiation de inc-0001 (MTTR) ?", k=2)
    assert top[0].kind == "incident" and top[0].doc == "journal/inc-0001"


def test_scores_are_ordered_and_extrait_is_clean(indexed):
    _, store = indexed
    passages = retrieve(store, "service_flood restart payment-api", k=4)
    scores = [p.score for p in passages]
    assert scores == sorted(scores, reverse=True)
    src = passages[0].as_source()
    assert set(src) >= {"doc", "extrait"} and not src["extrait"].startswith("[")
    assert len(src["extrait"]) <= 300


def test_unrelated_question_scores_low(indexed):
    _, store = indexed
    on_topic = retrieve(store, "procédure service_flood", k=1)[0].score
    off_topic = retrieve(store, "recette de la tarte aux pommes", k=1)[0].score
    assert off_topic < 0.05 < on_topic


def test_hash_embeddings_are_deterministic_and_normalized():
    emb = HashEmbeddings()
    a, b = emb.embed_query("Service Flood"), emb.embed_query("service_flood")
    assert emb.embed_query("Service Flood") == a
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    cos = sum(x * y for x, y in zip(a, b))
    assert cos > 0.5  # casse / séparateurs ne changent presque rien


def test_tokenizer_strips_accents_stopwords_and_splits_snake_case():
    assert tokenize("Les procédures de restauration") == ["procedure", "restauration"]
    assert {"service_flood", "service", "flood"} <= set(tokenize("service_flood"))
