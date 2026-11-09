import asyncio
import sys
from pathlib import Path

from app.common.database import get_engine, get_sessionmaker
from app.config.settings import get_settings
from app.features.menu.services.dish_seed_service import DishSeedService
from app.features.menu.services.exceptions import MenuSeedFileError
from app.infrastructure.storage import S3FileStorage


async def seed(directory: Path) -> None:
    settings = get_settings()
    if not settings.media.can_write:
        raise SystemExit("Set the MEDIA_* write keys in backend/.env to upload pictures.")
    storage = S3FileStorage(settings.media)
    try:
        async with get_sessionmaker()() as session:
            count = await DishSeedService(session, storage).run(directory=directory)
            await session.commit()
    except MenuSeedFileError as error:
        raise SystemExit(error.message) from None
    finally:
        await get_engine().dispose()
    print(f"Uploaded {count} pictures; {count} dishes in the file upserted.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.scripts.seed_menu <dir>")
    asyncio.run(seed(Path(sys.argv[1])))
