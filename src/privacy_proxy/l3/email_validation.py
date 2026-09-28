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

from presidio_analyzer import Pattern
from presidio_analyzer.predefined_recognizers import EmailRecognizer
from tldextract import TLDExtract

from .timeout_guard import TimeoutCallable, protect_callable

BUNDLED_SHA256 = "B69315C085D53972724B8F2DF111FFC329B0C84FE0A47D62C8C91655CC774A38"
VERSIONS = (("presidio-analyzer", "2.2.364"), ("tldextract", "5.3.2"), ("regex", "2026.9.3"))


class EmailConfigurationError(RuntimeError):
    """Configuration failure; reason codes only."""


def _snapshot_bytes() -> bytes:
    return resources.files("tldextract").joinpath(".tld_set_snapshot").read_bytes()


@dataclass(frozen=True, repr=False)
class _EmailValidation:
    _extractor: TLDExtract

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
    # Preserve the approved built-in pattern path, including its score/flags.
    if _pattern_signature(cast(Any, producer).patterns) != _pattern_signature(
        cast(Any, EmailRecognizer).PATTERNS
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
        validator = _EmailValidation(extractor)
        validator.check()
    except Exception:
        raise EmailConfigurationError("EMAIL_INITIALIZATION_FAILED") from None
    dynamic_producer = cast(Any, producer)
    dynamic_producer._email_validation = validator
    dynamic_producer.validate_result = protect_callable(validator)
    validate_email_configuration(producer)
