"""H2-R1 NC/OR/PR contracts: nullable consumption without confidence mutation."""

from itertools import permutations, product
from types import SimpleNamespace

import pytest

from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.schemas import DetectedPII, DetectionTier
from privacy_proxy.vault.crypto import VaultCrypto
from privacy_proxy.vault.store import InMemoryVaultStore
from privacy_proxy.vault.tokenizer import Tokenizer


@pytest.fixture(scope="module")
def service():
    return L3AnalyzerService()


@pytest.fixture
def tokenizer():
    crypto = VaultCrypto.from_base64(VaultCrypto.generate_key())
    return Tokenizer(InMemoryVaultStore(crypto), crypto)


def detection(start, end, confidence, source="SyntheticOverlapFixture", entity_type="PERSON_KO"):
    value = "ABCDEFGHIJ"[start:end]
    return DetectedPII(
        segment_id="nullable-test",
        start_idx=start,
        end_idx=end,
        entity_type=entity_type,
        confidence=confidence,
        source=source,
        tier=DetectionTier.MODEL,
        original_value=value,
        normalized=value,
    )


def assert_selection(inputs, expected):
    """Assert identities, payload preservation and unchanged caller list order."""
    before_ids = [id(d) for d in inputs]
    before_payloads = [d.model_dump() for d in inputs]
    result = Tokenizer._resolve_overlaps(inputs)
    assert len(result) == len(expected)
    assert all(actual is wanted for actual, wanted in zip(result, expected, strict=True))
    assert [id(d) for d in inputs] == before_ids
    assert [d.model_dump() for d in inputs] == before_payloads
    return result


@pytest.mark.parametrize(
    "raw,entity,value,generalized",
    [
        pytest.param(
            "고객은 30대입니다.", "AGE_GROUP", "30대", "고객은 30대입니다.", id="NC-01-03"
        ),
        pytest.param(
            "고객은 30대 초반입니다.",
            "AGE_GROUP",
            "30대 초반",
            "고객은 30대 초반입니다.",
            id="NC-02-04",
        ),
        pytest.param("고객은 32세입니다.", "AGE", "32세", "고객은 30대입니다.", id="NC-05"),
        pytest.param("audit@example.com", "EMAIL_ADDRESS", "audit@example.com", None, id="NC-06"),
    ],
)
@pytest.mark.parametrize("policy", ["TOKENIZE", "GENERALIZE"])
def test_nc_actual_nullable_consumption_and_pr_immutability(
    service, tokenizer, caplog, raw, entity, value, generalized, policy
):
    ds = service.analyze(raw, "nullable-caller-42", entities=[entity])
    assert len(ds) == 1
    d = ds[0]
    assert d.original_value == value
    assert d.confidence is None
    before = d.model_dump()
    wire_before = d.model_dump(mode="json")
    ids_before = [id(item) for item in ds]
    output = tokenizer.anonymize(
        session_id="nullable-session", raw_prompt=raw, detected_entities=ds, policy_action=policy
    )
    if policy == "GENERALIZE" and generalized is not None:
        assert output.anonymized_prompt == generalized
        assert output.vault_mapping == {}
    else:
        assert len(output.vault_mapping) == 1
        token, original = next(iter(output.vault_mapping.items()))
        assert original == value
        assert output.anonymized_prompt == raw[: d.start_idx] + token + raw[d.end_idx :]
        assert tokenizer.reveal("nullable-session", token) == value
        assert token not in caplog.text
    assert d.model_dump() == before
    assert d.model_dump(mode="json") == wire_before
    assert d.model_dump(mode="json")["confidence"] is None
    assert [id(item) for item in ds] == ids_before
    assert raw not in caplog.text
    assert value not in caplog.text
    assert str(output.vault_mapping) not in caplog.text


def test_nc07_multiple_actual_nullable_detections(service):
    raw = "고객은 30대입니다. 나이: 32세. audit@example.com"
    ds = service.analyze(raw, "nullable-caller-42", entities=["AGE_GROUP", "AGE", "EMAIL_ADDRESS"])
    assert len(ds) == 3
    assert all(d.confidence is None for d in ds)
    expected = sorted(ds, key=lambda d: d.start_idx)
    assert_selection(list(reversed(expected)), expected)


@pytest.mark.parametrize("confidence", [None, 0.0], ids=["OR-01", "OR-02"])
@pytest.mark.parametrize("reverse", [False, True])
def test_longer_span_first(confidence, reverse):
    long = detection(0, 6, confidence)
    short = detection(1, 4, 1.0)
    inputs = [long, short]
    assert_selection(inputs[::-1] if reverse else inputs, [long])


@pytest.mark.parametrize(
    "low,high",
    [
        pytest.param(0.0, 0.5, id="OR-03"),
        pytest.param(0.5, 1.0, id="OR-04"),
        pytest.param(None, 0.5, id="OR-05-half"),
        pytest.param(None, 1.0, id="OR-05-one"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_equal_span_different_rank(low, high, reverse):
    a, b = detection(0, 4, low), detection(0, 4, high)
    inputs = [a, b]
    assert_selection(inputs[::-1] if reverse else inputs, [b])


@pytest.mark.parametrize(
    "first,second",
    [
        pytest.param(None, 0.0, id="OR-06"),
        pytest.param(None, None, id="OR-07"),
        pytest.param(0.0, 0.0, id="OR-09-zero"),
        pytest.param(0.5, 0.5, id="OR-09-half"),
        pytest.param(1.0, 1.0, id="OR-09-one"),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_complete_tie_stable_input_order(first, second, reverse):
    a, b = detection(0, 4, first), detection(0, 4, second)
    inputs = [b, a] if reverse else [a, b]
    assert_selection(inputs, [inputs[0]])


@pytest.mark.parametrize("confidence", [None, 0.0, 0.5, 1.0])
def test_or08_equal_rank_earlier_start(confidence):
    early, later = detection(0, 4, confidence), detection(1, 5, confidence)
    assert_selection([later, early], [early])


@pytest.mark.parametrize("second_start", [2, 4], ids=["OR-10-adjacent", "OR-11-disjoint"])
def test_adjacent_and_disjoint_spans(second_start):
    a, b = detection(0, 2, None), detection(second_start, second_start + 2, 1.0)
    assert_selection([b, a], [a, b])


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("confidence", [None, 0.0, 0.5, 1.0])
def test_or12_no_source_or_entity_lexical_priority(reverse, confidence):
    a = detection(0, 4, confidence, source="AAA", entity_type="AGE_GROUP")
    b = detection(0, 4, confidence, source="ZZZ", entity_type="PERSON_KO")
    inputs = [b, a] if reverse else [a, b]
    assert_selection(inputs, [inputs[0]])


def historical_numeric_resolver(entities):
    """Frozen pre-remediation algorithm, used only for numeric parity evidence."""
    ordered = sorted(
        entities,
        key=lambda e: (
            -(e.end_idx - e.start_idx),
            -float(getattr(e, "confidence", 0.0)),
            e.start_idx,
        ),
    )
    kept = []
    for e in ordered:
        if all(e.end_idx <= k.start_idx or e.start_idx >= k.end_idx for k in kept):
            kept.append(e)
    return sorted(kept, key=lambda e: e.start_idx)


@pytest.mark.parametrize("scores", list(product((0.0, 0.5, 1.0), repeat=3)))
@pytest.mark.parametrize(
    "spans",
    [
        ((0, 4), (0, 4), (2, 6)),
        ((0, 6), (1, 3), (6, 9)),
        ((0, 2), (2, 4), (6, 9)),
    ],
)
def test_numeric_only_parity_for_all_input_permutations(scores, spans):
    ds = [detection(start, end, score) for (start, end), score in zip(spans, scores, strict=True)]
    for sequence in permutations(ds):
        inputs = list(sequence)
        assert_selection(inputs, historical_numeric_resolver(inputs))


def test_legacy_missing_confidence_preserves_zero_rank():
    missing = SimpleNamespace(start_idx=0, end_idx=4)
    zero = detection(0, 4, 0.0)
    high = detection(0, 4, 0.5)
    for inputs in ([missing, zero], [zero, missing]):
        result = Tokenizer._resolve_overlaps(inputs)
        assert len(result) == 1 and result[0] is inputs[0]
    result = Tokenizer._resolve_overlaps([missing, high])
    assert len(result) == 1 and result[0] is high
    assert not hasattr(missing, "confidence")


@pytest.mark.parametrize("malformed", ["", "not-a-number", []])
def test_malformed_non_null_confidence_is_not_swallowed(malformed):
    legacy = SimpleNamespace(start_idx=0, end_idx=4, confidence=malformed)
    with pytest.raises((TypeError, ValueError)):
        Tokenizer._resolve_overlaps([legacy])
