"""개인정보를 제외한 감사 메타데이터의 S3 저장."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config

from privacy_proxy.config import get_settings


def upload_audit_metadata(metadata: dict[str, Any]) -> None:
    """L9에서 선별한 메타데이터만 업로드한다."""
    settings = get_settings()

    if not settings.audit_s3_bucket.strip():
        raise ValueError("AUDIT_S3_BUCKET_REQUIRED")

    day = datetime.now(UTC).strftime("%Y/%m/%d")
    key = f"audit/{day}/{uuid.uuid4().hex}.json"

    client = boto3.client(
        "s3",
        region_name=settings.audit_s3_region,
        config=Config(
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 1},
        ),
    )

    try:
        client.put_object(
            Bucket=settings.audit_s3_bucket,
            Key=key,
            Body=json.dumps(
                metadata,
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
    finally:
        client.close()
