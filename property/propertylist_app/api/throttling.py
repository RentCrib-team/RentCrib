from rest_framework.throttling import UserRateThrottle
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.throttling import SimpleRateThrottle
import logging
from django.core.cache import caches
from rest_framework.settings import api_settings






class RegisterAnonThrottle(SimpleRateThrottle):
    """
    Anon (IP-based) throttle for registration. Blocks 3rd+ attempt in the time window.
    Scope name must exist in DEFAULT_THROTTLE_RATES.
    """
    scope = "register_anon"

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

    def get_cache_key(self, request, view):
        # Only throttle anonymous users (by IP).
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            return None

        ident = self.get_ident(request)  # IP address
        if not ident:
            return None

        return self.cache_format % {"scope": self.scope, "ident": ident}


class MessageUserThrottle(SimpleRateThrottle):
    """
    Per-user throttle for creating messages. Blocks 3rd+ attempt in the time window.
    Scope name must exist in DEFAULT_THROTTLE_RATES.
    """
    scope = "message_user"

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            # No user â€” donâ€™t throttle here (your messaging endpoint should require auth anyway).
            return None

        # Per-user key
        ident = str(user.pk)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class RoomCreateThrottle(SimpleRateThrottle):
    """
    Per-user throttle for creating room listings.

    Only authenticated POST requests are counted. Reading the public room
    list does not consume this throttle allowance.
    """

    scope = "room-create"

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

    def get_cache_key(self, request, view):
        if request.method != "POST":
            return None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        ident = str(user.pk)

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }



class  ReviewCreateThrottle(UserRateThrottle):
  scope = 'review-create'

class ReviewListThrottle(UserRateThrottle):
  scope = 'review-list'


class LoginScopedThrottle(ScopedRateThrottle):
    scope = "login"

class RegisterScopedThrottle(ScopedRateThrottle):
    scope = "register"

class PasswordResetScopedThrottle(ScopedRateThrottle):
    scope = "password-reset"

    def get_rate(self):
        """
        Read the current configured rate.

        This keeps production settings authoritative and allows focused tests
        to temporarily override this scope without stale DRF cached values.
        """
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

class PasswordResetConfirmScopedThrottle(ScopedRateThrottle):
    scope = "password-reset-confirm"




logger = logging.getLogger(__name__)

class ReportCreateScopedThrottle(ScopedRateThrottle):
    scope = "report-create"

    def get_rate(self):
        # Why this exists:
        # - In large pytest runs, DRF's THROTTLE_RATES can stay cached from earlier tests.
        # - Reading from api_settings each time guarantees override_settings is respected.
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)


class MessagingScopedThrottle(ScopedRateThrottle):
    scope = "messaging"



