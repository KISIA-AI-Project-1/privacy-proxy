"""AGE_GROUP v0.1: H1-R1 bounded personal statements, raw coordinates only.

This is a new capability, not a change to the historical D7-E AGE baseline.
No normalization, replacement, model inference, logging, or request state.
"""

from typing import Any, cast

import regex
from presidio_analyzer import EntityRecognizer, RecognizerResult

from .timeout_guard import protect_callable

MAX_ANCHOR_DISTANCE = 15
MAX_HORIZONTAL_GAP = 15
_REGEX_TIMEOUT = 0.1
_MAX_ANCHOR_LENGTH = 4  # Longest approved surface: 고객님은 / 연령대는.
_CLAUSE = regex.compile(r"[^.!?\r\n]+")
_FIELD = regex.compile(r"[^,;]+")
_CANDIDATE = regex.compile(r"(?<![\w.+,~\uff5e+\-\u2013\u2014])(?:[1-9]0)[ \t]{0,15}대")
_ANCHOR = regex.compile(
    r"(?<!\w)(?:(?P<label>연령대는|연령대가|연령대|연령은|연령이|연령|나이는|나이가|나이)"
    r"|(?P<person>고객님은|고객님이|고객은|고객이|본인은|본인이|저는|제가|나는|내가))(?!\w)"
)
_PERSON_GAP = regex.compile(r"[ \t]{1,15}(?:(?:현재|올해|지금)[ \t]{1,15})?")
_LABEL_GAP = regex.compile(
    r"(?:[ \t]{1,15}(?:(?:현재|올해|지금)[ \t]{1,15})?"
    r"|[ \t]{0,15}[:\uff1a=][ \t]{0,15}(?:(?:현재|올해|지금)[ \t]{1,15})?)"
)
_REFINED = regex.compile(r"초반|중반|후반")
_COPULA = regex.compile(r"(?:입니다|이에요|예요|이다|이고|이며)(?!\w)")
# Bounded suffix relations, not an arbitrary character-distance window.
_NON_PERSONAL_PREFIX = regex.compile(
    r"(?<!\w)(?:가입|권장|추천|신청|이용|제한|기준|대상|법정|의무|적용|지원|평균)"
    r"(?:[ \t]{0,15}(?:가능|필수|권장|기준|대상))?"
    r"[ \t]{0,15}(?:(?:고객님?|본인)[ \t]{1,15})?\Z"
)
_APPROXIMATE_PREFIX = regex.compile(r"(?<!\w)(?:약|대략)[ \t]{0,15}\Z")
# A rejected/deferred continuation must never fall back to the plain decade.
_REJECTED_SUFFIX = regex.compile(
    r"(?:[~\uff5e+\-\u2013\u2014]|이상|이하|미만|초과|부터|까지|제한|기준|대상"
    r"|정도|전후|쯤|가량|내외|안팎|처럼|보다|권장|추천"
    r"|(?:가|이)[ \t]{0,15}(?:아니|아님)|인[ \t]{1,15}경우"
    r"|(?:초중반|중후반|초)(?=$|[ \t]|입니다|이에요|예요|이다|이고|이며))"
)


def _horizontal_end(text: str, pos: int, limit: int) -> int | None:
    """Consume at most 15 raw horizontal characters; never truncate a gap."""
    end = pos
    while end < limit and text[end] in " \t":
        if end - pos == MAX_HORIZONTAL_GAP:
            return None
        end += 1
    if end < limit and text[end].isspace():
        return None  # Non-ASCII whitespace is deferred, not normalized.
    return end


class AgeGroupStatementRecognizer(EntityRecognizer):
    """Emit only RecognizerResult after the complete local relation passes."""

    name: str

    def __init__(self, supported_language: str = "ko") -> None:
        super().__init__(
            supported_entities=["AGE_GROUP"],
            supported_language=supported_language,
            name="AgeGroupStatementRecognizer",
        )

    def load(self) -> None:
        """No model or mutable matching state."""

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: Any = None
    ) -> list[RecognizerResult]:
        if "AGE_GROUP" not in entities:
            return []
        # Includes lazy iteration and semantic validation, not just finditer().
        return cast(list[RecognizerResult], protect_callable(self._analyze)(text))

    def _analyze(self, text: str) -> list[RecognizerResult]:
        results = []
        for clause in _CLAUSE.finditer(text, timeout=_REGEX_TIMEOUT):
            for field in _FIELD.finditer(text, *clause.span(), timeout=_REGEX_TIMEOUT):
                left, right = field.span()
                for candidate in _CANDIDATE.finditer(text, left, right, timeout=_REGEX_TIMEOUT):
                    end = self._valid_candidate(text, candidate, left, right)
                    if end is None:
                        continue
                    results.append(
                        RecognizerResult(
                            entity_type="AGE_GROUP",
                            start=candidate.start(),
                            end=end,
                            score=0.5,  # Internal only; not common confidence or tier evidence.
                            recognition_metadata={
                                RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                                RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                            },
                        )
                    )
        return results

    def _valid_candidate(
        self, text: str, candidate: Any, field_start: int, field_end: int
    ) -> int | None:
        start, end = cast(tuple[int, int], candidate.span())
        following = _horizontal_end(text, end, field_end)
        if following is None:
            return None
        refined = _REFINED.match(text, following, field_end, timeout=_REGEX_TIMEOUT)
        if refined:
            end = refined.end()
            following = _horizontal_end(text, end, field_end)
            if following is None:
                return None
        ending = _COPULA.match(text, following, field_end, timeout=_REGEX_TIMEOUT)
        if ending:
            after = _horizontal_end(text, ending.end(), field_end)
            if after is None or (after < len(text) and text[after] == "?"):
                return None
        else:
            if following < len(text) and text[following] == "?":
                return None
            if _REJECTED_SUFFIX.match(text, following, field_end, timeout=_REGEX_TIMEOUT):
                return None
            # A bare label value cannot hide an unapproved continuation behind
            # horizontal spacing, including a deferred refinement plus its ending.
            if following < field_end and (text[following].isalnum() or text[following] == "_"):
                return None
        window_start = max(field_start, start - MAX_ANCHOR_DISTANCE - _MAX_ANCHOR_LENGTH)
        for anchor in _ANCHOR.finditer(text, window_start, start, timeout=_REGEX_TIMEOUT):
            if not 1 <= start - anchor.end() <= MAX_ANCHOR_DISTANCE:
                continue
            gap = _LABEL_GAP if anchor.group("label") else _PERSON_GAP
            if not gap.fullmatch(text, anchor.end(), start, timeout=_REGEX_TIMEOUT):
                continue
            if _APPROXIMATE_PREFIX.search(
                text, field_start, anchor.start(), timeout=_REGEX_TIMEOUT
            ):
                continue
            # Target/statistical prefixes disqualify either anchor path locally.
            if _NON_PERSONAL_PREFIX.search(
                text, field_start, anchor.start(), timeout=_REGEX_TIMEOUT
            ):
                continue
            if anchor.group("label") or ending:
                return end
        return None
