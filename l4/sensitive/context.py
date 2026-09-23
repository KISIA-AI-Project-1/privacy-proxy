"""앵커 위치 직접 탐지 — sensitive 공용 인프라.

``l4/recognizers/context.py``의 ``has_anchor()``는 "이미 찾은 후보 근처에
앵커가 있는지"를 묻는다. 여기는 형식 정규식이 없어 후보 자체가 없다 —
앵커 단어가 곧 탐지 대상이라 앵커가 나타나는 위치 자체를 span으로 쓴다.
그래서 반대 방향의 함수가 필요하다: "텍스트에서 이 앵커들이 어디에
나타나는가."
"""

from __future__ import annotations


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def window_text(text: str, start: int, end: int, chars: int = 60) -> str:
    """앵커 span 주변 문자 윈도우 — 2단계 모델 입력용.

    문장 전체가 아니라 이 조각만 모델에 넣는다(``l4/sensitive/predict.py``,
    CLAUDE.md "2단계 설계"). 문자 단위로 넉넉히 자르고 최종 토큰 길이 제한은
    토크나이저의 truncation에 맡긴다 — 토큰 경계를 여기서 맞출 필요는 없다.
    """
    return text[max(0, start - chars) : end + chars]


def find_anchor_spans(
    text: str,
    anchors: list[str],
    word_start: frozenset[str] | set[str] = frozenset(),
) -> list[tuple[int, int, str]]:
    """텍스트에서 앵커 단어가 나타나는 모든 위치를 ``(start, end, anchor)``로.

    정규식이 아니라 ``str.find``로 찾는다. 짧은 앵커가 긴 앵커 안에 포함되는
    경우(예: "종교"가 "종교상"에 포함)도 둘 다 시도되어 결과적으로 한 번은
    잡힌다 — 배제하지 않는다, recall 우선.

    ``word_start`` 에 든 앵커는 앞 글자가 한글이 아닐 때만(문장 처음·공백·
    구두점 뒤) 인정한다. 그냥 부분 문자열로 찾으면 다른 단어의 일부가 걸린다 —
    "사별"은 "회사별"·"고객사별"에, "절에"는 "명절에"·"계절에"·"시절에"에.
    뒤쪽은 보지 않는다("사별하고"·"사별한"처럼 어미가 붙는 게 정상이라서).
    """
    spans: list[tuple[int, int, str]] = []
    for anchor in anchors:
        bounded = anchor in word_start
        start = 0
        while True:
            pos = text.find(anchor, start)
            if pos == -1:
                break
            if not (bounded and pos > 0 and _is_hangul(text[pos - 1])):
                spans.append((pos, pos + len(anchor), anchor))
            start = pos + 1
    return spans
