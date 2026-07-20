import uuid
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings

settings = get_settings()


@lru_cache
def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket() -> None:
    """Create the bucket if it is missing. Safe to call on every startup."""
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def build_key(user_id: uuid.UUID, filename: str, prefix: str = "resumes") -> str:
    return f"{prefix}/{user_id}/{uuid.uuid4()}/{filename}"


def upload_bytes(key: str, data: bytes, content_type: str) -> str:
    get_s3_client().put_object(
        Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type
    )
    return key


def download_bytes(key: str) -> bytes:
    obj = get_s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
    return obj["Body"].read()


def presigned_url(key: str, expires_in: int = 900) -> str:
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_in,
    )
