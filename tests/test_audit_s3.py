import json
import logging
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from audit import logger as audit_logger
from audit import s3_sink
from privacy_proxy.schemas import ProxyContext


@pytest.mark.asyncio
async def test_disabled_does_not_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 저장을 끄면 외부 업로드를 실행하지 않는다."""
    monkeypatch.setattr(
        audit_logger,
        "get_settings",
        lambda: SimpleNamespace(audit_s3_enabled=False),
    )
    uploader = Mock()
    monkeypatch.setattr(audit_logger, "upload_audit_metadata", uploader)

    await audit_logger._write_audit_log(ProxyContext())

    uploader.assert_not_called()


@pytest.mark.asyncio
async def test_upload_excludes_private_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원문·매핑·응답·신뢰하지 않는 오류 내용을 업로드하지 않는다."""
    monkeypatch.setattr(
        audit_logger,
        "get_settings",
        lambda: SimpleNamespace(audit_s3_enabled=True),
    )
    uploader = Mock()
    monkeypatch.setattr(audit_logger, "upload_audit_metadata", uploader)

    original = "private-person@example.com"
    placeholder = "【EMAIL_1】"
    context = ProxyContext(
        status="failed",
        error=f"failure: {original}",
        raw_prompt=original,
        anonymized_prompt=placeholder,
        vault_mapping={placeholder: original},
        reconstructed_body={"text": original},
        final_response_log=original,
    )

    await audit_logger._write_audit_log(context)

    uploader.assert_called_once()
    metadata = uploader.call_args.args[0]
    serialized = json.dumps(metadata)

    assert set(metadata) == {
        "session_id",
        "created_at",
        "status",
        "error_code",
        "risk_score",
        "risk_level",
        "policy_action",
        "latency_ms",
    }
    assert original not in serialized
    assert placeholder not in serialized
    assert metadata["error_code"] == "UNCLASSIFIED_FAILURE"


@pytest.mark.asyncio
async def test_upload_failure_preserves_response(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S3 실패 시 응답을 유지하고 민감한 예외 내용은 출력하지 않는다."""
    monkeypatch.setattr(
        audit_logger,
        "get_settings",
        lambda: SimpleNamespace(audit_s3_enabled=True),
    )
    uploader = Mock(side_effect=RuntimeError("private-person@example.com"))
    monkeypatch.setattr(audit_logger, "upload_audit_metadata", uploader)

    async def stream() -> AsyncGenerator[str, None]:
        yield "정상 응답"

    context = ProxyContext(final_response=stream())

    with caplog.at_level(logging.INFO, logger="audit.logger"):
        context = await audit_logger.audit_log_l9(context)
        uploader.assert_not_called()

        chunks = [chunk async for chunk in context.final_response]

    assert "".join(chunks) == "정상 응답"
    assert context.status == "success"
    assert context.error is None
    uploader.assert_called_once()

    metadata = uploader.call_args.args[0]
    assert "total_pipeline" in metadata["latency_ms"]
    assert "L9_S3_UPLOAD_FAILED" in caplog.text
    assert "private-person@example.com" not in caplog.text


def test_sink_uploads_json_to_audit_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 요청의 버킷·경로·본문·암호화 설정을 확인한다."""
    monkeypatch.setattr(
        s3_sink,
        "get_settings",
        lambda: SimpleNamespace(
            audit_s3_bucket="test-audit-bucket",
            audit_s3_region="ap-northeast-2",
        ),
    )
    client = Mock()
    monkeypatch.setattr(s3_sink.boto3, "client", Mock(return_value=client))

    metadata = {
        "session_id": "test-session",
        "status": "success",
    }
    s3_sink.upload_audit_metadata(metadata)

    client.put_object.assert_called_once()
    arguments = client.put_object.call_args.kwargs

    assert arguments["Bucket"] == "test-audit-bucket"
    assert arguments["Key"].startswith("audit/")
    assert arguments["Key"].endswith(".json")
    assert json.loads(arguments["Body"]) == metadata
    assert arguments["ContentType"] == "application/json"
    assert arguments["ServerSideEncryption"] == "AES256"
    client.close.assert_called_once()
