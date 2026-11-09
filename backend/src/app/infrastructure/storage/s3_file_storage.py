import boto3
from botocore.config import Config

from app.config.settings import MediaSettings


class S3FileStorage:
    def __init__(self, settings: MediaSettings) -> None:
        self._bucket = settings.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            config=Config(
                # OCI's S3 Compatibility API serves path-style URLs and rejects SigV2.
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                # botocore 1.36+ adds CRC checksums to every request by default; OCI rejects them.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def put(self, *, key: str, content: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=content, ContentType=content_type
        )
