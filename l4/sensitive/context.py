"""앵커 위치 직접 탐지 — sensitive 공용 인프라.

``l4/recognizers/context.py``의 ``has_anchor()``는 "이미 찾은 후보 근처에
앵커가 있는지"를 묻는다. 여기는 형식 정규식이 없어 후보 자체가 없다 —
앵커 단어가 곧 탐지 대상이라 앵커가 나타나는 위치 자체를 span으로 쓴다.
그래서 반대 방향의 함수가 필요하다: "텍스트에서 이 앵커들이 어디에
나타나는가."
"""

from __future__ import annotations


def find_anchor_spans(text: str, anchors: list[str]) -> list[tuple[int, int, str]]:
    """텍스트에서 앵커 단어가 나타나는 모든 위치를 ``(start, end, anchor)``로.

    정규식이 아니라 ``str.find``로 찾는다 — 앵커가 전부 완결된 한글 단어라
    (2자 이상, "빚"·"절" 등 일부 예외) ID 인식기의 ASCII 경계 문제
    (``l4/recognizers/patterns.py``의 ``_L``/``_R`` 참고)와 같은 종류의
    버그가 없다. 짧은 앵커가 긴 앵커 안에 포함되는 경우(예: "종교"가
    "종교상"에 포함)도 둘 다 시도되어 결과적으로 한 번은 잡힌다 — 배제하지
    않는다, recall 우선.
    """
    spans: list[tuple[int, int, str]] = []
    for anchor in anchors:
        start = 0
        while True:
            pos = text.find(anchor, start)
            if pos == -1:
                break
            spans.append((pos, pos + len(anchor), anchor))
            start = pos + 1
    return spans
