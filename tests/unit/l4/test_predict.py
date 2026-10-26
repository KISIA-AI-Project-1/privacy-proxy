"""predict_spans()의 entity_type 변환 테스트. 모델 없이 순수 로직만 본다.

``_apply_entity_type_map`` 은 torch 의존이 없는 순수 변환이라 여기서 직접
테스트한다 — 실제 추론 경로(``encode_and_merge`` 이후)는 가중치가 있어야
돌릴 수 있어서 이 저장소엔 별도 통합 테스트가 없다.
"""

from l4.ner.bio import Span
from l4.ner.labels import L4_ENTITY_TYPE_MAP, L4_ENTITY_TYPES
from l4.ner.predict import _apply_entity_type_map


def test_PS는_PERSON_KO로_바뀐다() -> None:
    spans = [Span(0, 3, "PS", "김철수")]

    assert _apply_entity_type_map(spans) == [Span(0, 3, "PERSON_KO", "김철수")]


def test_LC는_LOCATION_INFORMAL로_바뀐다() -> None:
    spans = [Span(0, 2, "LC", "서울")]

    assert _apply_entity_type_map(spans) == [Span(0, 2, "LOCATION_INFORMAL", "서울")]


def test_start_end_text는_그대로_보존된다() -> None:
    span = Span(4, 7, "PS", "이영희")

    result = _apply_entity_type_map([span])[0]

    assert (result.start, result.end, result.text) == (span.start, span.end, span.text)


def test_여러_span_순서가_보존된다() -> None:
    spans = [Span(0, 3, "PS", "김철수"), Span(4, 6, "LC", "서울")]

    assert _apply_entity_type_map(spans) == [
        Span(0, 3, "PERSON_KO", "김철수"),
        Span(4, 6, "LOCATION_INFORMAL", "서울"),
    ]


def test_빈_리스트는_빈_리스트() -> None:
    assert _apply_entity_type_map([]) == []


def test_L4_ENTITY_TYPE_MAP은_L4_ENTITY_TYPES를_전부_커버한다() -> None:
    """필터를 통과한 타입 중 매핑에 없는 게 있으면 KeyError로 바로 터진다.

    조용히 원래 이름("PS"/"LC")으로 새는 것보다, 매핑 추가를 깜빡했을 때
    바로 에러가 나는 게 낫다 — L5 계약 이름 누락은 곧 스키마 불일치다.
    """
    assert set(L4_ENTITY_TYPES) <= set(L4_ENTITY_TYPE_MAP)


def test_긴_입력은_끝까지_덮고_경계에_걸친_span도_온전히_한_번만_나온다(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """512토큰 초과 입력의 뒤쪽이 잘리면 안 된다. 스텁이 'X' 연속 구간을 PS로 잡는다."""
    import re

    from l4.ner import predict

    # 담당 구간 경계(255·510·765)를 가로지르는 20자 엔티티 3개 + 맨 끝 1개
    text = list("가" * 1200)
    for pos in (245, 500, 755, 1190):
        text[pos : pos + 10] = "X" * 10
    text = "".join(text)
    monkeypatch.setattr(
        predict,
        "encode_and_merge",
        lambda w, *a: (
            [Span(m.start(), m.end(), "PS", m.group()) for m in re.finditer("X+", w)],
            [],
        ),
    )
    monkeypatch.setattr(predict, "arbitrate_josa", lambda spans, offsets, w: spans)

    result = predict.predict_spans(text, None, None, None)  # type: ignore[arg-type]

    assert [(s.start, s.end) for s in result] == [
        (m.start(), m.end()) for m in re.finditer("X+", text)
    ]
    windows = predict._windows(len(text), 510)
    assert all(end - start <= 510 for start, end, _, _ in windows)
    assert windows[-1][1] == len(text)
