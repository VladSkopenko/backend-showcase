"""Imports every feature's models, so Base.metadata sees every table (ADR 11).

Alembic's env.py loads this module. Add each new feature's models here.
"""

from app.common.database import Base
from app.features.core.auth.models import OAuthAccount, RefreshToken, VerificationCode
from app.features.core.users.models import User

__all__ = ["Base", "OAuthAccount", "RefreshToken", "User", "VerificationCode"]
