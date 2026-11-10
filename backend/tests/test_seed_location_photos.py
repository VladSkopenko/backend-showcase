from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import MediaSettings
from app.features.core.locations.services.exceptions import LocationPhotoSeedError
from app.features.core.locations.services.location_photo_seed_service import (
    LocationPhotoSeedService,
)
from app.infrastructure.storage import S3FileStorage

pytestmark = pytest.mark.anyio


@pytest.fixture
def storage() -> S3FileStorage:
    return S3FileStorage(
        MediaSettings(
            s3_endpoint_url="http://127.0.0.1:9",
            region="eu-frankfurt-1",
            bucket="backend-showcase-media-test",
            access_key_id="test-access-key",
            secret_access_key=SecretStr("test-secret-key"),
            public_base_url="https://media.example.com/o",
        )
    )


async def test_missing_photos_fail_before_any_upload(
    tmp_path: Path, storage: S3FileStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    (tmp_path / "14-baratashvili-street.jpg").write_bytes(b"photo-bytes")

    async with session_factory() as session:
        with pytest.raises(LocationPhotoSeedError) as raised:
            await LocationPhotoSeedService(session, storage).run(directory=tmp_path)

    assert raised.value.code == "LOCATION_PHOTOS_MISSING"
    assert raised.value.message == (
        "Photos are missing for locations: 48-rustaveli-avenue, 9-abashidze-street"
    )
