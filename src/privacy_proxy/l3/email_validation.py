"""Pinned offline EMAIL validation; not domain existence or deliverability.

Preserve Presidio 2.2.364's fqdn != "" decision. No global monkey patches.
Each recognizer owns one initialized extractor; requests only read its suffix
data. Dependency upgrades require explicit revalidation of versions and resource.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from importlib import metadata, resources
from typing import Any, cast

import regex
from presidio_analyzer import Pattern
from presidio_analyzer.predefined_recognizers import EmailRecognizer
from tldextract import TLDExtract

from .timeout_guard import TimeoutCallable, protect_callable

BUNDLED_SHA256 = "B69315C085D53972724B8F2DF111FFC329B0C84FE0A47D62C8C91655CC774A38"

VERSIONS = (("presidio-analyzer", "2.2.364"), ("tldextract", "5.3.2"), ("regex", "2026.9.3"))

# Keep the built-in Unicode-domain pattern intact. It can consume attached
# Hangul into a candidate whose suffix validation fails. This additional
# pattern allows Unicode labels before the final dot. Its terminal label is
# ASCII/Punycode or an escaped Unicode TLD from this instance's pinned suffix
# authority, rather than an unrestricted Unicode word that absorbs Hangul.
# The pinned validator still decides whether the candidate suffix is valid.
# A word/hyphen continuation or dot + word after the Hangul run blocks the
# fallback, so a Unicode label continuing into another label is not truncated.
# The lookahead leaves sentence text outside the original raw email span.
EMAIL_KOREAN_SUFFIX_TEMPLATE = (
    r"\b((([!#$%&'*+\-/=?^_`{|}~\w])|"
    r"([!#$%&'*+\-/=?^_`{|}~\w]"
    r"[!#$%&'*+\-/=?^_`{|}~\.\w]{0,}"
    r"[!#$%&'*+\-/=?^_`{|}~\w]))"
    r"[@]"
    r"(?:\w+(?:-+\w+)*\.)+"
    r"{terminal})"
    r"(?=[\uac00-\ud7a3]+(?![\w-]|\.\w))"
)


def _configured_patterns(korean_suffix_pattern: str) -> list[Pattern]:
    # Detach mutable Pattern/compiled-regex state from the global originals.
    patterns = [
        Pattern(name=pattern.name, regex=pattern.regex, score=pattern.score)
        for pattern in EmailRecognizer.PATTERNS
    ]
    patterns.append(
        Pattern(
            name="Email Korean suffix (Medium)",
            regex=korean_suffix_pattern,
            score=0.5,
        )
    )
    return patterns


class EmailConfigurationError(RuntimeError):
    """Configuration failure; reason codes only."""


def _korean_suffix_pattern(extractor: TLDExtract) -> str:
    # The extractor has already loaded the hash-verified bundled snapshot.
    # Only literal, single-label public TLDs compatible with the built-in
    # domain grammar qualify; wildcard/exception/private rules are not literals.
    unicode_tlds = sorted(
        (
            suffix
            for suffix in extractor.tlds
            if not suffix.isascii()
            and "." not in suffix
            and regex.fullmatch(r"\w+(?:-+\w+)*", suffix)
        ),
        key=lambda suffix: (-len(suffix), suffix),
    )
    if not unicode_tlds:
        raise EmailConfigurationError("EMAIL_UNICODE_SUFFIX_CONFIGURATION")
    # Longest-first, atomic matching prevents backtracking to a shorter known
    # TLD and misclassifying the remainder of a longer TLD as sentence text.
    terminal = (
        "(?>"
        + "|".join(regex.escape(suffix) for suffix in unicode_tlds)
        + r"|[A-Za-z0-9_]+(?:-+[A-Za-z0-9_]+)*)"
    )
    return EMAIL_KOREAN_SUFFIX_TEMPLATE.replace("{terminal}", terminal)


def _snapshot_bytes() -> bytes:
    return resources.files("tldextract").joinpath(".tld_set_snapshot").read_bytes()


@dataclass(frozen=True, repr=False)
class _EmailValidation:
    _extractor: TLDExtract
    _korean_suffix_pattern: str

    def check(self) -> None:
        e = self._extractor
        if (
            type(e) is not TLDExtract
            or e.suffix_list_urls != ()
            or e._cache.enabled
            or not e.fallback_to_snapshot
            or e.include_psl_private_domains
            or e.extra_suffixes != ()
            or e._extractor is None
        ):
            raise EmailConfigurationError("EMAIL_EXTRACTOR_CONFIGURATION")

    def __call__(self, text: str) -> bool:
        self.check()
        return bool(self._extractor(text).fqdn)


def _pattern_signature(
    patterns: Iterable[Pattern],
) -> list[tuple[str, str, float]]:
    return [(pattern.name, pattern.regex, pattern.score) for pattern in patterns]


def validate_email_configuration(
    producer: EmailRecognizer,
) -> None:
    validator = getattr(producer, "_email_validation", None)
    guard = producer.validate_result
    if (
        type(producer) is not EmailRecognizer
        or type(validator) is not _EmailValidation
        or type(guard) is not TimeoutCallable
        or guard.callback is not validator
    ):
        raise EmailConfigurationError("EMAIL_VALIDATOR_CONFIGURATION")
    validator.check()
    # Preserve the approved instance-local EMAIL pattern path, including
    # its score. Do not mutate EmailRecognizer.PATTERNS globally.
    if _pattern_signature(cast(Any, producer).patterns) != _pattern_signature(
        _configured_patterns(validator._korean_suffix_pattern)
    ):
        raise EmailConfigurationError("EMAIL_PATTERN_CONFIGURATION")


def configure_email(
    producer: EmailRecognizer,
) -> None:
    """Attach one instance-local validator, preserving producer identity."""
    if hasattr(producer, "_email_validation"):
        validate_email_configuration(producer)
        return
    if (
        type(producer) is not EmailRecognizer
        or getattr(producer.validate_result, "__func__", None)
        is not EmailRecognizer.validate_result
    ):
        raise EmailConfigurationError("EMAIL_PRODUCER_CONFIGURATION")
    try:
        if any(metadata.version(name) != expected for name, expected in VERSIONS):
            raise EmailConfigurationError("EMAIL_DEPENDENCY_VERSION")
        if sha256(_snapshot_bytes()).hexdigest().upper() != BUNDLED_SHA256:
            raise EmailConfigurationError("EMAIL_SUFFIX_SNAPSHOT_HASH")
        extractor = TLDExtract(
            cache_dir=None,
            suffix_list_urls=(),
            fallback_to_snapshot=True,
            include_psl_private_domains=False,
            extra_suffixes=(),
        )
        # Initialize the bundled suffix trie before exposing the recognizer.
        extractor("example.com")
        validator = _EmailValidation(extractor, _korean_suffix_pattern(extractor))
        validator.check()
    except Exception:
        raise EmailConfigurationError("EMAIL_INITIALIZATION_FAILED") from None
    dynamic_producer = cast(Any, producer)
    dynamic_producer.patterns = _configured_patterns(validator._korean_suffix_pattern)
    dynamic_producer._email_validation = validator
    dynamic_producer.validate_result = protect_callable(validator)
    validate_email_configuration(producer)
