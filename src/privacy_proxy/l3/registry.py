"""Eleven exact L3 producers; not the PD-014 source naming registry."""

from typing import Any, cast

from presidio_analyzer import RecognizerRegistry
from presidio_analyzer.predefined_recognizers import (
    EmailRecognizer,
    KrBrnRecognizer,
    KrDriverLicenseRecognizer,
    KrFrnRecognizer,
    KrPassportRecognizer,
    KrRrnRecognizer,
    PhoneRecognizer,
)

from .age_group_recognizer import AgeGroupStatementRecognizer
from .age_recognizer import AgeStatementRecognizer
from .date_of_birth_recognizer import DateOfBirthRecognizer
from .email_validation import configure_email, validate_email_configuration
from .location_recognizer import LocationRecognizer

PRODUCER_TYPES: dict[str, type[Any]] = {
    "KR_RRN": KrRrnRecognizer,
    "KR_FRN": KrFrnRecognizer,
    "KR_PASSPORT": KrPassportRecognizer,
    "KR_DRIVER_LICENSE": KrDriverLicenseRecognizer,
    "KR_BRN": KrBrnRecognizer,
    "PHONE_NUMBER": PhoneRecognizer,
    "EMAIL_ADDRESS": EmailRecognizer,
    "AGE": AgeStatementRecognizer,
    "AGE_GROUP": AgeGroupStatementRecognizer,
    "DATE_OF_BIRTH": DateOfBirthRecognizer,
    "LOCATION": LocationRecognizer,
}
SUPPORTED_ENTITIES = tuple(PRODUCER_TYPES)


class RegistryConfigurationError(RuntimeError):
    """Invalid capability/provenance configuration."""


def validate_registry(
    registry: RecognizerRegistry,
) -> dict[str, Any]:
    if registry.supported_languages != ["ko"]:
        raise RegistryConfigurationError("REGISTRY_LANGUAGE")
    producers: dict[str, Any] = {}
    identifiers: set[str] = set()
    for producer in registry.recognizers:
        entities = producer.supported_entities
        if producer.supported_language != "ko" or len(entities) != 1:
            raise RegistryConfigurationError("PRODUCER_CAPABILITY")
        entity = entities[0]
        if entity not in PRODUCER_TYPES or type(producer) is not PRODUCER_TYPES[entity]:
            raise RegistryConfigurationError("UNVERIFIED_PRODUCER")
        if type(producer) is PhoneRecognizer and (
            producer.supported_regions != ("KR",) or producer.leniency != 1
        ):
            raise RegistryConfigurationError("PHONE_PARSER_CONFIGURATION")
        if type(producer) is EmailRecognizer:
            validate_email_configuration(producer)
        if entity in producers or producer.id in identifiers:
            raise RegistryConfigurationError("DUPLICATE_PRODUCER")
        if not isinstance(cast(Any, producer).name, str) or not cast(Any, producer).name.strip():
            raise RegistryConfigurationError("PRODUCER_NAME")
        if cast(Any, producer).name.strip() in ("L3", "L4") or not producer.id:
            raise RegistryConfigurationError("PRODUCER_IDENTITY")
        producers[entity] = producer
        identifiers.add(producer.id)
    if set(producers) != set(SUPPORTED_ENTITIES):
        raise RegistryConfigurationError("INCOMPLETE_REGISTRY")
    return producers


def build_registry() -> RecognizerRegistry:
    registry = RecognizerRegistry(
        recognizers=[
            cls(supported_language="ko", supported_regions=("KR",))
            if cls is PhoneRecognizer
            else cls(supported_language="ko")
            for cls in PRODUCER_TYPES.values()
        ],
        supported_languages=["ko"],
    )
    for producer in registry.recognizers:
        if type(producer) is EmailRecognizer:
            configure_email(producer)
    validate_registry(registry)
    return registry
