"""D7 AGE v0.1: bounded extraction followed by local semantic validation.

Distance counts raw Python characters from anchor end (particle included) to
surface start (optional 만 included), inclusive maximum 15. Clauses end at
CR/LF, '.', '!', '?'. Only ASCII space/tab are horizontal spacing; at most 15
per internal gap. Labels accept a value; person anchors require a copula.
No normalization, mutable request evidence, external models, or logging.
"""

from typing import Any, cast

import regex
from presidio_analyzer import EntityRecognizer, RecognizerResult

from .timeout_guard import protect_callable

MAX_ANCHOR_DISTANCE = 15
_REGEX_TIMEOUT = 0.1
_CLAUSE = regex.compile(r"[^.!?\r\n]+")
_CANDIDATE = regex.compile(
    r"(?<![\w.+,~\uff5e+\-])(?:만[ \t]{0,15})?(?P<number>[0-9]{1,3})[ \t]{0,15}(?:세|살)"
)
_ANCHOR = regex.compile(
    r"(?<!\w)(?:(?P<label>나이|연령)(?:는|은|가|이)?"
    r"|(?P<person>저|제|나|내|고객(?:님)?|본인)(?:는|은|가|이))"
)
_GAP = regex.compile(r"(?:[ \t:\uff1a=]|현재|올해|지금){0,15}")
_ENDING = regex.compile(r"[ \t]{0,15}(?:입니다|이에요|예요|이다|이고|이며)(?!\w)")
_RANGE_SUFFIX = regex.compile(r"[ \t]{0,15}[~\uff5e\-\u2013\u2014]")
# Local engineering bound, not a universal age rule: 15 existing horizontal
# spaces + the longest comparative prefix (더/덜 + 7 spaces + 많/적) = 24.
_SEMANTIC_WINDOW = 24
_APPROXIMATE_BEFORE_ANCHOR = regex.compile(r"(?<!\w)(?:약|대략)[ \t]{0,15}\Z")
_APPROXIMATE_AFTER = regex.compile(r"[ \t]{0,15}(?:내외|안팎|가량|정도|전후|쯤)")
# Explicit cue + stem still needs predicate continuation, checked below.
# Preserve the existing cue-less complete forms and strong relative nouns.
_RELATIVE_AFTER = regex.compile(
    r"[ \t]{0,15}(?:(?P<comparative>(?:더|덜)[ \t]{0,7}(?:많|적))"
    r"|(?:많|적)(?:습니다|아요|어요|네요|다|고|으며|은|게)(?!\w)"
    r"|차이|연상|연하|터울)"
)
# Initial syllables of continuation categories, not complete surface endings
# or lexical exceptions. This is a conservative boundary check, not morphology.
_PREDICATE_CONTINUATION_STARTS = frozenset(
    "고게지으"  # connective (including the 으- connection in 으면/으며)
    "은던"  # attributive
    "았었겠더"  # tense/modality
    "습다네아어"  # sentence-ending continuation
)
_THRESHOLD_AFTER = regex.compile(r"[ \t]{0,15}(?:이상|이하|미만|초과|부터|까지|제한|기준|대상)")
_POLICY_BEFORE_LABEL = regex.compile(
    r"(?<!\w)(?:가입|권장|신청|이용|제한|기준|대상|법정|의무|적용)"
    r"(?:[ \t]{0,15}(?:가능|필수|권장|기준|대상))?[ \t]{0,15}\Z"
)
# Preserve the existing succession/generation guard. Approximation, comparison
# and policy guards below inspect only the current candidate/anchor relation.
_EXCLUSION = regex.compile(r"재벌|창업")


def _has_predicate_continuation(text: str, stem_end: int, clause_end: int) -> bool:
    """Inspect only the next raw character; never scan or cross the clause."""
    if stem_end == clause_end:
        return True
    next_char = text[stem_end]
    if not (next_char.isalnum() or next_char == "_"):
        return True  # Termination/separator after the comparative stem.
    return next_char in _PREDICATE_CONTINUATION_STARTS


class AgeStatementRecognizer(EntityRecognizer):
    """Emit AGE only after all context and semantic checks have succeeded."""

    name: str

    def __init__(self, supported_language: str = "ko") -> None:
        super().__init__(
            supported_entities=["AGE"],
            supported_language=supported_language,
            name="AgeStatementRecognizer",
        )

    def load(self) -> None:
        """Compiled, immutable module patterns need no model initialization."""

    def analyze(
        self, text: str, entities: list[str], nlp_artifacts: Any = None
    ) -> list[RecognizerResult]:
        if "AGE" not in entities:
            return []
        # The existing guard encloses iteration AND validation, not merely
        # iterator creation. Lazy timeouts cannot escape as successful results.
        return cast(list[RecognizerResult], protect_callable(self._analyze)(text))

    def _analyze(self, text: str) -> list[RecognizerResult]:
        results = []
        for clause in _CLAUSE.finditer(text, timeout=_REGEX_TIMEOUT):
            left, right = clause.span()
            if _EXCLUSION.search(text, left, right, timeout=_REGEX_TIMEOUT):
                continue
            for candidate in _CANDIDATE.finditer(text, left, right, timeout=_REGEX_TIMEOUT):
                if not self._valid_candidate(text, candidate, left, right):
                    continue
                results.append(
                    RecognizerResult(
                        entity_type="AGE",
                        start=candidate.start(),
                        end=candidate.end(),
                        score=0.5,  # Internal Presidio score, never common confidence/tier evidence.
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                            RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                        },
                    )
                )
        return results

    def _valid_candidate(
        self, text: str, candidate: Any, clause_start: int, clause_end: int
    ) -> bool:
        number = candidate.group("number")
        if (len(number) > 1 and number[0] == "0") or int(number) > 120:
            return False
        start, end = candidate.span()
        # At most 24 consumed characters plus one boundary character.
        # Use the real clause end, not an artificial window-edge boundary.
        relative = _RELATIVE_AFTER.match(text, end, clause_end, timeout=_REGEX_TIMEOUT)
        if relative and (
            relative.group("comparative") is None
            or _has_predicate_continuation(text, relative.end(), clause_end)
        ):
            return False
        post_end = min(clause_end, end + _SEMANTIC_WINDOW)
        if any(
            guard.match(text, end, post_end, timeout=_REGEX_TIMEOUT)
            for guard in (_APPROXIMATE_AFTER, _THRESHOLD_AFTER)
        ):
            return False
        # A value must end at a token boundary or an explicitly recognized
        # copula. This rejects 세기/세트/세대 rather than consuming a substring.
        if _RANGE_SUFFIX.match(text, end, clause_end, timeout=_REGEX_TIMEOUT):
            return False
        ending = _ENDING.match(text, end, clause_end, timeout=_REGEX_TIMEOUT)
        if end < clause_end and (text[end].isalnum() or text[end] == "_") and not ending:
            return False
        # Anchor length is bounded (at most five characters); search only a
        # small raw window. regex pos preserves true lookbehind at window start.
        window_start = max(clause_start, start - MAX_ANCHOR_DISTANCE - 5)
        for anchor in _ANCHOR.finditer(text, window_start, start, timeout=_REGEX_TIMEOUT):
            distance = start - anchor.end()
            if distance > MAX_ANCHOR_DISTANCE:
                continue
            if not _GAP.fullmatch(text, anchor.end(), start, timeout=_REGEX_TIMEOUT):
                continue
            if _APPROXIMATE_BEFORE_ANCHOR.search(
                text,
                max(clause_start, anchor.start() - _SEMANTIC_WINDOW),
                anchor.start(),
                timeout=_REGEX_TIMEOUT,
            ):
                continue
            if anchor.group("label") and _POLICY_BEFORE_LABEL.search(
                text,
                max(clause_start, anchor.start() - _SEMANTIC_WINDOW),
                anchor.start(),
                timeout=_REGEX_TIMEOUT,
            ):
                continue
            if anchor.group("label") or ending:
                return True
        return False
