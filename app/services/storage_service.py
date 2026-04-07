"""Service de stockage fichiers — S3/DigitalOcean Spaces avec fallback local."""

import logging
import os
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

LOCAL_UPLOAD_DIR = Path("/tmp/klassci-uploads")


def _get_s3_client():
    """Crée un client boto3 configuré pour DO Spaces."""
    return boto3.client(
        "s3",
        region_name=settings.DO_SPACES_REGION,
        endpoint_url=settings.DO_SPACES_ENDPOINT,
        aws_access_key_id=settings.DO_SPACES_KEY,
        aws_secret_access_key=settings.DO_SPACES_SECRET,
    )


def _generate_key(original_name: str, folder: str) -> str:
    """Génère un nom de fichier unique pour éviter les collisions."""
    ext = Path(original_name).suffix.lower()
    unique_id = uuid.uuid4().hex[:16]
    return f"{folder}/{unique_id}{ext}"


async def upload_file(
    file_bytes: bytes,
    original_name: str,
    content_type: str,
    folder: str = "documents",
) -> str:
    """Upload un fichier et retourne son URL.

    Utilise DO Spaces si configuré, sinon fallback vers stockage local.
    """
    key = _generate_key(original_name, folder)

    if settings.DO_SPACES_KEY:
        return _upload_to_s3(file_bytes, key, content_type)

    return _upload_to_local(file_bytes, key)


def _upload_to_s3(file_bytes: bytes, key: str, content_type: str) -> str:
    """Upload vers S3/DO Spaces."""
    try:
        client = _get_s3_client()
        client.put_object(
            Bucket=settings.DO_SPACES_BUCKET,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
            ACL="private",
        )
        url = f"{settings.DO_SPACES_ENDPOINT}/{settings.DO_SPACES_BUCKET}/{key}"
        logger.info("File uploaded to S3: %s", key)
        return url
    except (BotoCoreError, ClientError):
        logger.exception("S3 upload failed for key=%s", key)
        raise


def _upload_to_local(file_bytes: bytes, key: str) -> str:
    """Fallback : stockage local dans /tmp/klassci-uploads/."""
    file_path = LOCAL_UPLOAD_DIR / key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(file_bytes)
    logger.info("File stored locally: %s", file_path)
    return f"file://{file_path}"
