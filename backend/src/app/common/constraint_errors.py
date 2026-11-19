from collections.abc import Callable, Mapping
from types import TracebackType

from sqlalchemy.exc import IntegrityError


class ConstraintErrors:
    def __init__(self, errors: Mapping[str, Callable[[], Exception]]) -> None:
        self._errors = errors

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not isinstance(exc, IntegrityError):
            return
        error = self._errors.get(self._constraint_name(exc))
        if error is not None:
            raise error() from exc

    @staticmethod
    def _constraint_name(exc: IntegrityError) -> str:
        driver_error = exc.orig.__cause__ if exc.orig is not None else None
        name = getattr(driver_error, "constraint_name", None)
        return name if isinstance(name, str) else ""
