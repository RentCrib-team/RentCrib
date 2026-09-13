from functools import wraps

from django.utils import timezone

from propertylist_app.models import AuditLog, Room


def _is_moderation_hidden(room):
    """Return whether the room's current hidden state was imposed by moderation."""
    latest_action = (
        AuditLog.objects
        .filter(
            action__in=["room.hide", "room.set_status"],
            extra_data__room_id=room.pk,
        )
        .order_by("-timestamp")
        .first()
    )

    if latest_action is None:
        return False

    if latest_action.action == "room.hide":
        return True

    return (
        latest_action.action == "room.set_status"
        and (latest_action.extra_data or {}).get("status") == Room.Lifecycle.HIDDEN
    )


def install_paid_hidden_room_reactivation():
    """
    Extend Room.set_status for the paid hidden->active transition.

    Owner-unpublished or expiry-hidden rooms may become active again once they
    have a current paid advertising period. Moderation-hidden rooms remain
    hidden even when payment succeeds, so payment can be recorded without
    silently overriding a moderation decision.
    """
    original = Room.set_status

    if getattr(original, "_rentcrib_paid_hidden_reactivation", False):
        return

    @wraps(original)
    def set_status_with_paid_hidden_reactivation(self, new_status):
        if (
            self.status == Room.Lifecycle.HIDDEN
            and new_status == Room.Lifecycle.ACTIVE
        ):
            if _is_moderation_hidden(self):
                return

            today = timezone.localdate()
            if self.paid_until and self.paid_until >= today:
                self.status = Room.Lifecycle.ACTIVE
                return

        return original(self, new_status)

    set_status_with_paid_hidden_reactivation._rentcrib_paid_hidden_reactivation = True
    Room.set_status = set_status_with_paid_hidden_reactivation
