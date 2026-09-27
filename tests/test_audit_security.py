import logging

import pytest

from audit.logger import _print_log
from privacy_proxy.schemas import DetectedPII, DetectionTier, ProxyContext


def test_audit_log_excludes_pii_mapping_and_restored_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_value = "private-person@example.com"
    placeholder = "<EMAIL_ADDRESS_1>"
    context = ProxyContext(
        raw_prompt=private_value,
        detected_entities=[
            DetectedPII(
                entity_type="EMAIL_ADDRESS",
                original_value=private_value,
                start_idx=0,
                end_idx=len(private_value),
                confidence=1.0,
                tier=DetectionTier.DETERMINISTIC,
                source="TEST",
            )
        ],
        anonymized_prompt=placeholder,
        vault_mapping={placeholder: private_value},
        token_types={placeholder: "EMAIL_ADDRESS"},
        reconstructed_body={"messages": [{"content": placeholder}]},
        final_response_log=f"restored {private_value}",
    )

    with caplog.at_level(logging.INFO, logger="audit.logger"):
        _print_log(context)

    output = caplog.text
    assert private_value not in output
    assert placeholder not in output
    assert "detected_entities" not in output
    assert "vault_mapping" not in output
    assert "final_response" not in output


def test_audit_log_replaces_untrusted_error_text(caplog: pytest.LogCaptureFixture) -> None:
    private_value = "private-person@example.com"
    context = ProxyContext(status="failed", error=f"failure: {private_value}")

    with caplog.at_level(logging.INFO, logger="audit.logger"):
        _print_log(context)

    output = caplog.text
    assert private_value not in output
    assert "UNCLASSIFIED_FAILURE" in output


def test_audit_log_rejects_code_shaped_untrusted_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    untrusted_value = "PRIVATE_CUSTOMER_123456"
    context = ProxyContext(status="failed", error=untrusted_value)

    with caplog.at_level(logging.INFO, logger="audit.logger"):
        _print_log(context)

    output = caplog.text
    assert untrusted_value not in output
    assert "UNCLASSIFIED_FAILURE" in output
