import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common import clock
from app.config.settings import MediaSettings
from app.features.menu.enums import DishCategory
from app.features.menu.services.dish_seed_service import DishSeedService
from app.features.menu.services.exceptions import MenuSeedFileError
from app.infrastructure.storage import S3FileStorage
from app.model_registry import Dish

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def entry(slug: str, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "description": f"About {slug}",
        "category": "DESSERT",
        "price_cents": 650,
        "weight_grams": 180,
        "calories": 420,
        "protein": "6g",
        "fats": "22-24g",
        "carbs": "48g",
        "vitamins": "A, D",
        "is_available": True,
        "popularity": 3,
        "image": f"{slug}.webp",
    }
    values.update(overrides)
    return values


def write_seed(directory: Path, entries: list[dict[str, Any]]) -> Path:
    directory.mkdir(exist_ok=True)
    (directory / "dishes.json").write_text(json.dumps(entries))
    for item in entries:
        image = item.get("image")
        if isinstance(image, str):
            (directory / image).write_bytes(b"picture-bytes")
    return directory


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "now", lambda: NOW)


@pytest.fixture
def storage() -> S3FileStorage:
    # Real storage pointed at a closed local port: any upload attempt fails loudly.
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


async def load_dishes(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Dish]:
    async with session_factory() as session:
        dishes = (await session.scalars(select(Dish))).all()
    return {dish.slug: dish for dish in dishes}


async def save_seed(
    session_factory: async_sessionmaker[AsyncSession], storage: S3FileStorage, directory: Path
) -> None:
    async with session_factory() as session:
        await DishSeedService(session, storage).save(
            entries=DishSeedService.load(directory=directory)
        )
        await session.commit()


def test_load_parses_entries_and_derives_keys_and_content_types(tmp_path: Path) -> None:
    directory = write_seed(
        tmp_path / "menu",
        [
            entry("lava-cake"),
            entry("tomato-soup", category="APPETIZER", image="soup.jpg"),
            entry("steak", category="MAIN_COURSE", image="steak.png"),
        ],
    )

    entries = DishSeedService.load(directory=directory)

    assert [item.slug for item in entries] == ["lava-cake", "tomato-soup", "steak"]
    assert [item.category for item in entries] == [
        DishCategory.DESSERT,
        DishCategory.APPETIZER,
        DishCategory.MAIN_COURSE,
    ]
    assert [item.image_key for item in entries] == [
        "dishes/lava-cake.webp",
        "dishes/tomato-soup.jpg",
        "dishes/steak.png",
    ]
    assert [item.content_type for item in entries] == ["image/webp", "image/jpeg", "image/png"]
    assert entries[1].image == "soup.jpg"


@pytest.mark.parametrize(
    "bad_entry",
    [
        entry("bad", category="SOUP"),
        entry("bad", price_cents=0),
        entry("bad", weight_grams=-1),
        entry("bad", image="bad.gif"),
        entry("Bad Slug"),
        {key: value for key, value in entry("bad").items() if key != "name"},
        entry("bad", unexpected="field"),
    ],
)
async def test_a_bad_entry_fails_before_anything_is_written(
    tmp_path: Path,
    storage: S3FileStorage,
    session_factory: async_sessionmaker[AsyncSession],
    bad_entry: dict[str, Any],
) -> None:
    directory = write_seed(tmp_path / "menu", [entry("good"), bad_entry])

    async with session_factory() as session:
        with pytest.raises(MenuSeedFileError):
            await DishSeedService(session, storage).run(directory=directory)

    assert await load_dishes(session_factory) == {}


@pytest.mark.parametrize("problem", ["missing_picture", "duplicate_slug", "not_json", "no_file"])
async def test_a_bad_file_fails_before_anything_is_written(
    tmp_path: Path,
    storage: S3FileStorage,
    session_factory: async_sessionmaker[AsyncSession],
    problem: str,
) -> None:
    directory = write_seed(tmp_path / "menu", [entry("good"), entry("other")])
    if problem == "missing_picture":
        (directory / "other.webp").unlink()
    elif problem == "duplicate_slug":
        write_seed(directory, [entry("good"), entry("good", image="other.webp")])
    elif problem == "not_json":
        (directory / "dishes.json").write_text("{not json")
    else:
        (directory / "dishes.json").unlink()

    async with session_factory() as session:
        with pytest.raises(MenuSeedFileError):
            await DishSeedService(session, storage).run(directory=directory)

    assert await load_dishes(session_factory) == {}


async def test_save_inserts_new_dishes_with_created_at_by_file_position(
    tmp_path: Path, storage: S3FileStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    directory = write_seed(
        tmp_path / "menu", [entry("first", popularity=8), entry("second"), entry("third")]
    )

    await save_seed(session_factory, storage, directory)

    dishes = await load_dishes(session_factory)
    assert dishes["first"].created_at == NOW
    assert dishes["second"].created_at == NOW - timedelta(minutes=1)
    assert dishes["third"].created_at == NOW - timedelta(minutes=2)
    assert dishes["first"].popularity == 8
    assert dishes["first"].image_key == "dishes/first.webp"
    assert dishes["first"].category is DishCategory.DESSERT
    assert dishes["first"].price_cents == 650
    assert dishes["first"].fats == "22-24g"


async def test_saving_twice_updates_content_and_keeps_id_popularity_and_created_at(
    tmp_path: Path, storage: S3FileStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    directory = write_seed(tmp_path / "menu", [entry("cake", popularity=3), entry("pie")])
    await save_seed(session_factory, storage, directory)
    before = await load_dishes(session_factory)
    async with session_factory() as session:
        await session.execute(update(Dish).where(Dish.slug == "cake").values(popularity=42))
        await session.commit()

    write_seed(
        directory,
        [entry("pie"), entry("cake", name="Honey Cake", price_cents=700, popularity=0)],
    )
    await save_seed(session_factory, storage, directory)

    after = await load_dishes(session_factory)
    assert set(after) == {"cake", "pie"}
    assert after["cake"].id == before["cake"].id
    assert after["cake"].popularity == 42
    assert after["cake"].created_at == before["cake"].created_at
    assert after["pie"].created_at == before["pie"].created_at
    assert after["cake"].name == "Honey Cake"
    assert after["cake"].price_cents == 700


async def test_dishes_missing_from_the_file_stay(
    tmp_path: Path, storage: S3FileStorage, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    directory = write_seed(tmp_path / "menu", [entry("cake"), entry("pie")])
    await save_seed(session_factory, storage, directory)

    write_seed(directory, [entry("cake")])
    await save_seed(session_factory, storage, directory)

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Dish))
    assert count == 2


async def test_saving_again_touches_updated_at_only_for_changed_dishes(
    tmp_path: Path,
    storage: S3FileStorage,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    later = NOW + timedelta(days=1)
    directory = write_seed(tmp_path / "menu", [entry("cake"), entry("pie")])
    await save_seed(session_factory, storage, directory)

    monkeypatch.setattr(clock, "now", lambda: later)
    write_seed(directory, [entry("cake", price_cents=700), entry("pie")])
    await save_seed(session_factory, storage, directory)

    dishes = await load_dishes(session_factory)
    assert dishes["cake"].updated_at == later
    assert dishes["pie"].updated_at == NOW
