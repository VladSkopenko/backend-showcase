from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.config.settings import MediaSettings
from app.features.core.menu.enums import DishCategory
from app.features.core.menu.services.dish_seed_service import DishSeedService
from app.features.core.menu.services.exceptions import MenuSeedFileError
from app.infrastructure.storage import S3FileStorage
from app.model_registry import Dish

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


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


@pytest.fixture
async def empty_menu(connection: AsyncConnection) -> None:
    await connection.execute(text("DELETE FROM dishes"))


async def add_dishes(session_factory: async_sessionmaker[AsyncSession], *image_keys: str) -> None:
    async with session_factory() as session:
        for image_key in image_keys:
            slug = Path(image_key).stem
            session.add(
                Dish(
                    slug=slug,
                    name=slug.title(),
                    description=f"About {slug}",
                    category=DishCategory.DESSERT,
                    price_cents=650,
                    weight_grams=180,
                    calories=420,
                    protein="6g",
                    fats="22g",
                    carbs="48g",
                    vitamins="A, D",
                    is_available=True,
                    popularity=0,
                    prep_minutes=10,
                    image_key=image_key,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        await session.commit()


async def stored_dishes(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[tuple[str, str, object]]:
    async with session_factory() as session:
        rows = await session.execute(
            select(Dish.slug, Dish.image_key, Dish.updated_at).order_by(Dish.slug)
        )
        return [(slug, image_key, updated_at) for slug, image_key, updated_at in rows]


def write_pictures(directory: Path, image_keys: list[str]) -> None:
    for image_key in image_keys:
        (directory / Path(image_key).name).write_bytes(f"bytes of {image_key}".encode())


async def test_the_seed_uploads_the_pictures_named_by_the_dishes_and_writes_nothing(
    tmp_path: Path,
    storage: S3FileStorage,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = await stored_dishes(session_factory)
    image_keys = [image_key for _, image_key, _ in before]
    assert image_keys
    write_pictures(tmp_path, image_keys)
    uploads: list[tuple[str, bytes, str]] = []
    monkeypatch.setattr(
        storage,
        "put",
        lambda *, key, content, content_type: uploads.append((key, content, content_type)),
    )

    async with session_factory() as session:
        count = await DishSeedService(session, storage).run(directory=tmp_path)
        assert not (session.new or session.dirty or session.deleted)

    assert count == len(image_keys)
    assert sorted(uploads) == sorted(
        (image_key, f"bytes of {image_key}".encode(), "image/jpeg") for image_key in image_keys
    )
    assert await stored_dishes(session_factory) == before


async def test_a_missing_picture_fails_before_any_upload(
    tmp_path: Path, storage: S3FileStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    image_keys = [image_key for _, image_key, _ in await stored_dishes(session_factory)]
    write_pictures(tmp_path, image_keys[:-1])

    async with session_factory() as session:
        with pytest.raises(MenuSeedFileError) as raised:
            await DishSeedService(session, storage).run(directory=tmp_path)

    assert Path(image_keys[-1]).name in raised.value.message


@pytest.mark.usefixtures("empty_menu")
async def test_pictures_get_the_content_type_of_their_suffix(
    tmp_path: Path,
    storage: S3FileStorage,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_dishes(session_factory, "dishes/cake.webp", "dishes/soup.png", "dishes/stew.jpg")
    write_pictures(tmp_path, ["dishes/cake.webp", "dishes/soup.png", "dishes/stew.jpg"])
    uploads: list[tuple[str, str]] = []
    monkeypatch.setattr(
        storage,
        "put",
        lambda *, key, content, content_type: uploads.append((key, content_type)),
    )

    async with session_factory() as session:
        await DishSeedService(session, storage).run(directory=tmp_path)

    assert sorted(uploads) == [
        ("dishes/cake.webp", "image/webp"),
        ("dishes/soup.png", "image/png"),
        ("dishes/stew.jpg", "image/jpeg"),
    ]


@pytest.mark.usefixtures("empty_menu")
async def test_an_unsupported_picture_type_fails_before_any_upload(
    tmp_path: Path, storage: S3FileStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_dishes(session_factory, "dishes/apple.jpg", "dishes/zest.gif")
    write_pictures(tmp_path, ["dishes/apple.jpg", "dishes/zest.gif"])

    async with session_factory() as session:
        with pytest.raises(MenuSeedFileError) as raised:
            await DishSeedService(session, storage).run(directory=tmp_path)

    assert "zest.gif" in raised.value.message


@pytest.mark.usefixtures("empty_menu")
async def test_an_empty_menu_fails_and_asks_for_the_migrations(
    tmp_path: Path, storage: S3FileStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        with pytest.raises(MenuSeedFileError) as raised:
            await DishSeedService(session, storage).run(directory=tmp_path)

    assert "run the migrations first" in raised.value.message
