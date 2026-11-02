"""L6 정책 일관성·왕복 복원 테스트.

실행:
    uv run pytest tests/vault/test_policy_consistency.py -v

"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest

from privacy_proxy.vault.crypto import VaultCrypto
from privacy_proxy.vault.store import InMemoryVaultStore
from privacy_proxy.vault.tokenizer import (
    BASE_SPECS,
    EntityActionKind,
    EntityMismatchError,
    Tokenizer,
    UnsupportedEntityError,
    is_known,
)

SID = "sess-1"


# ----------------------------------------------------------------- 헬퍼
@dataclass
class FakeEntity:
    """DetectedPII 와 같은 속성만 가진 가짜 탐지 결과(L6 는 duck typing 으로 읽는다)."""

    entity_type: str
    start_idx: int
    end_idx: int
    original_value: str
    segment_id: str = "seg-1"
    confidence: float | None = 0.9


def span(prompt: str, value: str, entity_type: str, nth: int = 0) -> FakeEntity:
    idx = -1
    for _ in range(nth + 1):
        idx = prompt.index(value, idx + 1)
    return FakeEntity(entity_type, idx, idx + len(value), value)


def make_tokenizer(strict: bool = False):
    crypto = VaultCrypto(b"k" * 32)
    store = InMemoryVaultStore(crypto)
    return Tokenizer(store, crypto, strict=strict), store


def run(prompt, pairs, *, action=None, policies=None, strict=False, tk=None, sid=SID):
    """pairs: [(entity_type, value[, nth])...]"""
    tk = tk or make_tokenizer(strict)[0]
    ents = [span(prompt, p[1], p[0], p[2] if len(p) > 2 else 0) for p in pairs]
    res = tk.anonymize(
        session_id=sid,
        raw_prompt=prompt,
        detected_entities=ents,
        policy_action=action,
        entity_policies=policies,
    )
    return tk, ents, res


def restore(tk, text, result, sid=SID):
    """L8 이 하는 일을 흉내: 가명을 reveal 로 원문 복원(긴 가명부터)."""
    for pseud in sorted(result.vault_mapping, key=len, reverse=True):
        text = text.replace(pseud, tk.reveal(sid, pseud))
    return text


# L5 정책 <-> L6 결과 대조 가드 (운영 코드에 옮겨 쓸 수 있다)
_EXPECT = {
    "TOKENIZE": {"TOKENIZE"},
    "GENERALIZE": {"GENERALIZE"},
    "ALLOW": {"KEEP", "GENERALIZE"},  # 주소는 ALLOW 여도 최소 일반화
}
_EXCEPT = {
    ("PRODUCT_ITEM", "TOKENIZE"): {"GENERALIZE"},  # 상품은 가역 토큰 금지
    ("AGE_GROUP", "GENERALIZE"): {"KEEP"},  # 이미 대략적 값
}


def check_l5_l6(entity_policies, result):
    """불일치 목록을 돌려준다. 비어 있어야 정상."""
    bad = []
    for a in result.entity_actions:
        l5 = entity_policies.get((a.segment_id, a.start_idx, a.end_idx))
        allowed = _EXCEPT.get((a.entity_type, l5)) or _EXPECT.get(l5, set())
        if a.action.value == "SKIPPED" or l5 is None or a.action.value not in allowed:
            bad.append((a.entity_type, l5, a.action.value))
    return bad


# ----------------------------------------------------------------- 1. 직접식별자는 정책과 무관하게 항상 TOKENIZE
DIRECT_SAMPLES = {
    "KR_PASSPORT": "M12345678",
    "CUSTOMER_ID": "C-000123",
    "TRACKING_NUMBER": "1234567890123",
    "ORDER_ID": "ORD-20240101-77",
    "ACCOUNT_NUMBER": "110-123-456789",
    "KR_RRN": "900101-1234567",
    "PHONE_NUMBER": "010-1234-5678",
    "EMAIL_ADDRESS": "a@b.com",
    "PERSON_KO": "김철수",
    "SENSITIVE_HEALTH": "당뇨",
}


@pytest.mark.parametrize("entity_type", sorted(DIRECT_SAMPLES))
@pytest.mark.parametrize("action", ["TOKENIZE", "GENERALIZE", "ALLOW", None])
def test_direct_identifiers_always_tokenized(entity_type, action):
    value = DIRECT_SAMPLES[entity_type]
    prompt = f"값 {value} 입니다"
    _, _, res = run(prompt, [(entity_type, value)], action=action)
    assert res.entity_actions[0].action is EntityActionKind.TOKENIZE
    assert value not in res.anonymized_prompt


def test_all_base_specs_covered_by_samples_or_known():
    # BASE_SPECS 에 타입이 추가되면 위 샘플표에도 추가하라는 알림
    missing = sorted(
        set(BASE_SPECS)
        - set(DIRECT_SAMPLES)
        - {
            "PERSON_EN",
            "CUSTOMS_CLEARANCE_ID",
            "KR_FRN",
            "KR_DRIVER_LICENSE",
            "KR_BRN",
            "DATE_OF_BIRTH",
            "SENSITIVE_SEX_LIFE",
        }
    )
    assert missing == []


# ----------------------------------------------------------------- 2. 이름·전화번호 왕복
def test_roundtrip_name_and_phone():
    prompt = "김철수가 010-1234-5678로 문의했어요. 김철수 고객은 이영희와 통화."
    tk, _, res = run(
        prompt,
        [
            ("PERSON_KO", "김철수"),
            ("PHONE_NUMBER", "010-1234-5678"),
            ("PERSON_KO", "김철수", 1),
            ("PERSON_KO", "이영희"),
        ],
        action="TOKENIZE",
    )
    out = res.anonymized_prompt
    for raw in ("김철수", "010-1234-5678", "이영희"):
        assert raw not in out
    assert out.count("홍길동") == 2  # 같은 사람 -> 같은 가명
    assert "성춘향" in out  # 다른 사람 -> 다른 가명
    llm = "홍길동 고객님, 【PHONE_1】 로 연락드리겠습니다. 성춘향님도 확인했습니다."
    assert (
        restore(tk, llm, res)
        == "김철수 고객님, 010-1234-5678 로 연락드리겠습니다. 이영희님도 확인했습니다."
    )


def test_same_value_gets_same_pseudonym_across_requests_in_session():
    tk, _ = make_tokenizer()
    _, _, r1 = run("김철수 문의", [("PERSON_KO", "김철수")], action="TOKENIZE", tk=tk)
    _, _, r2 = run("다시 김철수 문의", [("PERSON_KO", "김철수")], action="TOKENIZE", tk=tk)
    assert r1.anonymized_prompt.split()[0] == r2.anonymized_prompt.split()[1]


def test_phone_format_variants_share_one_token():
    p = "010-1234-5678 그리고 +82 10 1234 5678"
    _, _, res = run(
        p,
        [("PHONE_NUMBER", "010-1234-5678"), ("PHONE_NUMBER", "+82 10 1234 5678")],
        action="TOKENIZE",
    )
    assert res.anonymized_prompt == "【PHONE_1】 그리고 【PHONE_1】"


def test_vault_mapping_matches_reveal_for_format_variants():
    p = "010-1234-5678 그리고 +82 10 1234 5678"
    tk, _, res = run(
        p,
        [("PHONE_NUMBER", "010-1234-5678"), ("PHONE_NUMBER", "+82 10 1234 5678")],
        action="TOKENIZE",
    )
    for pseud, orig in res.vault_mapping.items():
        assert tk.reveal(SID, pseud) == orig


def test_reveal_is_isolated_per_session():
    tk, _, _ = run("김철수 문의", [("PERSON_KO", "김철수")], action="TOKENIZE")
    assert tk.reveal("other-sess", "홍길동") is None


def test_ciphertext_bound_to_session_and_namespace():
    from privacy_proxy.vault.crypto import VaultCryptoError

    (
        tk,
        store,
    ) = make_tokenizer()
    run("010-1234-5678", [("PHONE_NUMBER", "010-1234-5678")], action="TOKENIZE", tk=tk)
    rec = store.get_by_pseudonym(SID, "【PHONE_1】")
    with pytest.raises(VaultCryptoError):
        tk.crypto.decrypt(rec.original_enc, aad=f"{SID}|WRONG")


def test_real_name_in_prompt_not_reused_as_pseudonym():
    prompt = "고객 홍길동님이 김철수 대신 문의"
    _, _, res = run(prompt, [("PERSON_KO", "김철수")], action="TOKENIZE")
    assert "홍길동" in res.anonymized_prompt  # 원문 홍길동은 그대로
    assert res.anonymized_prompt.count("홍길동") == 1  # 가명이 홍길동이면 2가 된다


def test_concurrent_requests_same_value_one_pseudonym():
    tk, _ = make_tokenizer()
    results, errors = [], []

    def worker():
        try:
            _, _, r = run("김철수 문의", [("PERSON_KO", "김철수")], action="TOKENIZE", tk=tk)
            results.append(r.anonymized_prompt)
        except Exception as e:
            errors.append(e)

    ts = [threading.Thread(target=worker) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors
    assert len(set(results)) == 1


# ----------------------------------------------------------------- 조사 보정
@pytest.mark.parametrize(
    "prompt,name,expected",
    [
        ("김철수가 왔다", "김철수", "홍길동이 왔다"),
        ("김철수를 만났다", "김철수", "홍길동을 만났다"),
        ("김철수와 함께", "김철수", "홍길동과 함께"),
        ("김철수로 변경", "김철수", "홍길동으로 변경"),
    ],
)
def test_josa_follows_pseudonym_batchim(prompt, name, expected):
    _, _, res = run(prompt, [("PERSON_KO", name)], action="TOKENIZE")
    assert res.anonymized_prompt == expected


def test_josa_not_touched_for_non_hangul_token():
    _, _, res = run(
        "010-1234-5678이 내 번호", [("PHONE_NUMBER", "010-1234-5678")], action="TOKENIZE"
    )
    assert res.anonymized_prompt == "【PHONE_1】이 내 번호"


# ----------------------------------------------------------------- 3. 상품명
@pytest.mark.parametrize("action", ["GENERALIZE", "TOKENIZE"])
def test_product_generalized_not_in_vault(action):
    p = "임신테스트기와 헤어에센스를 주문. 임신테스트기 환불?"
    (
        tk,
        store,
    ) = make_tokenizer()
    _, _, res = run(
        p,
        [
            ("PRODUCT_ITEM", "임신테스트기"),
            ("PRODUCT_ITEM", "헤어에센스"),
            ("PRODUCT_ITEM", "임신테스트기", 1),
        ],
        action=action,
        tk=tk,
    )
    assert res.anonymized_prompt == "상품과 상품을 주문. 상품 환불?"
    assert res.vault_mapping == {} and res.token_types == {}
    assert store._data == {} and store._counters == {}  # InMemory 내부 확인
    assert tk.reveal(SID, "상품") is None
    assert {a.action for a in res.entity_actions} == {EntityActionKind.GENERALIZE}


@pytest.mark.parametrize("action", ["ALLOW", None])
def test_product_generalizes_when_allowed(action):
    _, _, res = run("임신테스트기 주문", [("PRODUCT_ITEM", "임신테스트기")], action=action)
    assert res.anonymized_prompt == "상품 주문"
    assert res.vault_mapping == {}
    assert res.token_types == {}
    assert {a.action for a in res.entity_actions} == {EntityActionKind.GENERALIZE}


# ----------------------------------------------------------------- 준식별자·주소·구매패턴 정책표
@pytest.mark.parametrize(
    "etype,value,action,expected_out,expected_kind",
    [
        ("AGE", "34세", "GENERALIZE", "30대", "GENERALIZE"),
        ("AGE", "34세", "TOKENIZE", "【AGE_1】", "TOKENIZE"),
        ("AGE", "34세", "ALLOW", "34세", "KEEP"),
        ("AGE_GROUP", "30대", "GENERALIZE", "30대", "KEEP"),  # 의도된 통과
        ("AGE_GROUP", "30대", "TOKENIZE", "【AGE_GROUP_1】", "TOKENIZE"),
        ("LOCATION", "관악구", "GENERALIZE", "【LOCATION】", "GENERALIZE"),
        ("LOCATION", "서울 마포구 신림동", "GENERALIZE", "서울", "GENERALIZE"),
        ("LOCATION", "관악구", "ALLOW", "관악구", "KEEP"),
        (
            "ADDRESS",
            "서울특별시 마포구 월드컵북로4길 77",
            "ALLOW",
            "서울특별시 마포구",
            "GENERALIZE",
        ),
        ("ADDRESS_ROAD", "월드컵북로4길 77", None, "【ADDRESS】", "GENERALIZE"),
        ("PURCHASE_PATTERN", "정기배송", "TOKENIZE", "정기배송", "KEEP"),
        ("PURCHASE_PATTERN", "정기배송", "GENERALIZE", "정기배송", "KEEP"),
    ],
)
def test_policy_table(etype, value, action, expected_out, expected_kind):
    prompt = f"({value})"
    _, _, res = run(prompt, [(etype, value)], action=action)
    assert res.anonymized_prompt == f"({expected_out})"
    assert res.entity_actions[0].action.value == expected_kind


def test_province_abbreviation_kept_on_generalize():
    _, _, res = run("서울 거주", [("LOCATION", "서울")], action="GENERALIZE")
    assert res.anonymized_prompt == "서울 거주"


# ----------------------------------------------------------------- 4. 정책 불일치가 조용히 새지 않는가
def test_unsupported_type_blocked_in_strict():
    with pytest.raises(UnsupportedEntityError):
        run(
            "카드 1234-5678-9012-3456",
            [("CREDIT_CARD", "1234-5678-9012-3456")],
            action="TOKENIZE",
            strict=True,
        )


def test_unsupported_type_is_reported_when_not_strict():
    _, _, res = run(
        "카드 1234-5678-9012-3456",
        [("CREDIT_CARD", "1234-5678-9012-3456")],
        action="TOKENIZE",
        strict=False,
    )
    assert res.skipped_types == ["CREDIT_CARD"]
    assert res.entity_actions[0].action is EntityActionKind.SKIPPED
    # 주의: 이 모드에서는 원문이 그대로 남는다 -> 운영은 strict=True 여야 함
    assert "1234-5678-9012-3456" in res.anonymized_prompt


def test_policy_key_miss_raises_error():
    """항목별 정책 키가 누락되면 요청 단위 정책으로 폴백하지 않고 예외를 발생시킨다."""
    p = "34세 고객"
    e = span(p, "34세", "AGE")
    ok = {("seg-1", e.start_idx, e.end_idx): "GENERALIZE"}
    miss = {("seg-2", e.start_idx, e.end_idx): "GENERALIZE"}

    tk, _ = make_tokenizer()
    r_ok = tk.anonymize(
        session_id=SID,
        raw_prompt=p,
        detected_entities=[e],
        policy_action="TOKENIZE",
        entity_policies=ok,
    )
    assert r_ok.anonymized_prompt.startswith("30대")

    tk2, _ = make_tokenizer()
    with pytest.raises(ValueError, match="L5 entity policy missing"):
        tk2.anonymize(
            session_id=SID,
            raw_prompt=p,
            detected_entities=[e],
            policy_action="TOKENIZE",
            entity_policies=miss,
        )


def test_product_not_leaked_when_policy_key_missing():
    _, _, res = run(
        "임신테스트기 주문", [("PRODUCT_ITEM", "임신테스트기")], action="ALLOW", policies={}
    )
    assert "임신테스트기" not in res.anonymized_prompt


def test_mismatch_guard_detects_missing_key_and_skipped():
    p = "임신테스트기 주문"
    e = span(p, "임신테스트기", "PRODUCT_ITEM")
    tk, _ = make_tokenizer()
    res = tk.anonymize(
        session_id=SID,
        raw_prompt=p,
        detected_entities=[e],
        policy_action="ALLOW",
        entity_policies={},
    )
    assert check_l5_l6({}, res)  # 키 없음 -> 불일치로 잡힘

    res2 = make_tokenizer(False)[0].anonymize(
        session_id=SID,
        raw_prompt="카드 1234",
        detected_entities=[span("카드 1234", "1234", "CREDIT_CARD")],
        policy_action="TOKENIZE",
    )
    key = ("seg-1", res2.entity_actions[0].start_idx, res2.entity_actions[0].end_idx)
    assert check_l5_l6({key: "TOKENIZE"}, res2)  # SKIPPED -> 불일치로 잡힘


def test_mismatch_guard_passes_for_consistent_policies():
    p = "김철수 34세 임신테스트기 정기배송"
    ents = [
        span(p, "김철수", "PERSON_KO"),
        span(p, "34세", "AGE"),
        span(p, "임신테스트기", "PRODUCT_ITEM"),
        span(p, "정기배송", "PURCHASE_PATTERN"),
    ]
    l5 = {
        ("seg-1", ents[0].start_idx, ents[0].end_idx): "TOKENIZE",
        ("seg-1", ents[1].start_idx, ents[1].end_idx): "GENERALIZE",
        ("seg-1", ents[2].start_idx, ents[2].end_idx): "GENERALIZE",
        ("seg-1", ents[3].start_idx, ents[3].end_idx): "ALLOW",
    }
    tk, _ = make_tokenizer(strict=True)
    res = tk.anonymize(
        session_id=SID,
        raw_prompt=p,
        detected_entities=ents,
        policy_action="TOKENIZE",
        entity_policies=l5,
    )
    assert check_l5_l6(l5, res) == []
    assert res.anonymized_prompt == "홍길동 30대 상품 정기배송"


def test_span_mismatch_raises_without_leaking_values():
    with pytest.raises(EntityMismatchError) as ei:
        tk, _ = make_tokenizer()
        tk.anonymize(
            session_id=SID,
            raw_prompt="김철수 문의",
            detected_entities=[FakeEntity("PERSON_KO", 0, 3, "이영희")],
            policy_action="TOKENIZE",
        )
    assert "김철수" not in str(ei.value) and "이영희" not in str(ei.value)


def test_overlapping_spans_longest_wins_single_replacement():
    p = "서울특별시 마포구 거주"
    big = span(p, "서울특별시 마포구", "ADDRESS")
    small = span(p, "서울특별시", "LOCATION")
    _, _, res = run_entities(p, [small, big], action="TOKENIZE")
    assert len(res.entity_actions) == 1 and res.entity_actions[0].entity_type == "ADDRESS"


def run_entities(prompt, ents, *, action=None):
    tk, _ = make_tokenizer()
    return (
        tk,
        ents,
        tk.anonymize(
            session_id=SID, raw_prompt=prompt, detected_entities=ents, policy_action=action
        ),
    )


# ----------------------------------------------------------------- 계약 검사 (L5 타입 ⊆ L6 지원 타입)
def test_l5_supported_types_are_known_to_l6():
    mod = pytest.importorskip("privacy_proxy.risk.entity_contract")
    unknown = sorted(t for t in mod.L5_SUPPORTED_ENTITY_TYPES if not is_known(t))
    assert unknown == [], f"L6 가 모르는 L5 타입: {unknown}"
