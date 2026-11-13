"""Imports every feature's models, so Base.metadata sees every table (ADR 11).

Alembic's env.py loads this module. Add each new feature's models here.
"""

from app.common.database import Base
from app.features.core.auth.models import OAuthAccount, RefreshToken, VerificationCode
from app.features.core.bookings.models import Booking, BookingParticipant, Guest
from app.features.core.locations.models import DiningTable, Location
from app.features.core.menu.models import Dish
from app.features.core.notifications.models import Notification
from app.features.core.users.models import User
from app.features.invites.models import BookingInvite
from app.features.preorder.models import PreorderItem

__all__ = [
    "Base",
    "Booking",
    "BookingInvite",
    "BookingParticipant",
    "DiningTable",
    "Dish",
    "Guest",
    "Location",
    "Notification",
    "OAuthAccount",
    "PreorderItem",
    "RefreshToken",
    "User",
    "VerificationCode",
]
