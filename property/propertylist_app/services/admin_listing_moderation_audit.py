from functools import wraps

from propertylist_app.admin_api.listings import services as listing_services
from propertylist_app.models import AuditLog, Room


def install_admin_listing_moderation_audit():
    """Record admin listing hide/restore decisions for payment reactivation policy."""
    original = listing_services.update_listing_action

    if getattr(original, "_rentcrib_admin_listing_moderation_audit", False):
        return

    @wraps(original)
    def update_listing_action_with_audit(room_id, action):
        result = original(room_id, action)

        if action == "hide":
            AuditLog.objects.create(
                user=None,
                action="room.hide",
                extra_data={
                    "room_id": room_id,
                    "source": "admin_listing_action",
                },
            )
        elif action in {"approve", "restore", "publish"}:
            AuditLog.objects.create(
                user=None,
                action="room.set_status",
                extra_data={
                    "room_id": room_id,
                    "status": Room.Lifecycle.ACTIVE,
                    "source": "admin_listing_action",
                },
            )

        return result

    update_listing_action_with_audit._rentcrib_admin_listing_moderation_audit = True
    listing_services.update_listing_action = update_listing_action_with_audit
