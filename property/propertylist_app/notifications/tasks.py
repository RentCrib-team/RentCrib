from __future__ import annotations

from datetime import date, timedelta

from celery import shared_task
from django.conf import settings
from django.template import Context, Template
from django.utils import timezone

from notifications.models import (
    DeliveryAttempt,
    NotificationPreference,
    NotificationTemplate,
    OutboundNotification,
)
from notifications.services import send_mail
from propertylist_app.models import (
    Booking,
    Notification,
    Room,
    UserProfile,
)
from propertylist_app.notifications.utils import create_in_app_notification_if_allowed


def _frontend_base_url() -> str:
    """
    Base URL for deep links in emails.
    Use settings.FRONTEND_BASE_URL if you have it, otherwise default to localhost.
    """
    return getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")


def _inbox_link() -> str:
    """
    Deep link to inbox/messages page.
    Adjust the path to match your frontend route when ready.
    """
    return f"{_frontend_base_url()}/inbox"


def _html_email(subject: str, body_text: str, button_url: str, button_text: str = "Open inbox") -> str:
    """
    Simple HTML email with a button.
    """
    safe_body = (body_text or "").replace("\n", "<br>")
    return f"""
    <!doctype html>
    <html>
      <body style="margin:0; padding:0; background:#f6f7fb; font-family: Arial, sans-serif;">
        <div style="max-width:640px; margin:0 auto; padding:24px;">
          <div style="background:#ffffff; border-radius:14px; padding:22px; box-shadow:0 6px 18px rgba(0,0,0,0.06);">
            <h2 style="margin:0 0 12px 0; font-size:18px; color:#111827;">{subject}</h2>
            <p style="margin:0 0 18px 0; font-size:14px; color:#374151; line-height:1.6;">{safe_body}</p>

            <a href="{button_url}"
               style="display:inline-block; padding:12px 16px; border-radius:10px; text-decoration:none;
                      background:#1d4e89; color:#ffffff; font-size:14px;">
              {button_text}
            </a>

            <p style="margin:18px 0 0 0; font-size:12px; color:#6b7280;">
              If the button does not work, copy and paste this link:<br>
              <span style="color:#111827;">{button_url}</span>
            </p>
          </div>
        </div>
      </body>
    </html>
    """.strip()


def _render_template_string(tpl: str, ctx: dict) -> str:
    """
    Render a Django-template string like 'Hi {{ room_title }}' using ctx dict.
    """
    if not tpl:
        return ""
    return Template(tpl).render(Context(ctx or {}))


def _enrich_context(ctx: dict) -> dict:
    """
    Make templates like {{ room.title }} work even if we only stored room_id.
    """
    ctx = dict(ctx or {})

    # Ensure common URLs exist
    ctx.setdefault("renew_url", _inbox_link())
    ctx.setdefault("cta_url", _inbox_link())

    # Build nested room dict if template expects {{ room.title }}
    room_id = ctx.get("room_id")
    if room_id and "room" not in ctx:
        room = Room.objects.filter(id=room_id).only("title", "paid_until").first()
        if room:
            ctx["room"] = {
                "title": getattr(room, "title", ""),
                "paid_until": str(getattr(room, "paid_until", "")),
            }

    return ctx


def _allowed_to_send_template(*, profile: UserProfile, template_key: str) -> bool:
    """
    Maps email templates to Account -> Notifications toggles.
    - marketing templates: require marketing_consent
    - everything else: treated as RentOut updates (notify_rentout_updates)
    """
    key = (template_key or "").strip().lower()
    if key.startswith("marketing_"):
        return bool(getattr(profile, "marketing_consent", False))
    return bool(getattr(profile, "notify_rentout_updates", True))


@shared_task(name="notifications.tasks.notify_listing_expiring")
def notify_listing_expiring(
    days_ahead: int = 3,
    room_id: int | None = None,
) -> None:
    """
    Queue one expiry-reminder email per active paid listing.

    Production:
    - Celery Beat runs this once daily at 07:00.
    - A listing receives one reminder when it falls within three days of expiry.

    QA:
    - `room_id` allows one specific staging listing to be targeted safely.
    """
    template = (
        NotificationTemplate.objects.filter(
            key="listing.expiring",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        ).first()
    )
    if not template:
        return

    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    rooms = (
        Room.objects.select_related("property_owner")
        .filter(
            status=Room.Lifecycle.ACTIVE,
            paid_until__gte=today,
            paid_until__lte=cutoff,
        )
    )

    if room_id is not None:
        rooms = rooms.filter(pk=room_id)

    for room in rooms:
        owner = room.property_owner
        profile, _ = UserProfile.objects.get_or_create(user=owner)

        already_queued = OutboundNotification.objects.filter(
            user=owner,
            channel=template.CHANNEL_EMAIL,
            template_key=template.key,
            context__room_id=room.pk,
        ).exists()

        if (
            not already_queued
            and _allowed_to_send_template(
                profile=profile,
                template_key=template.key,
            )
        ):
            OutboundNotification.objects.create(
                user=owner,
                channel=template.CHANNEL_EMAIL,
                template_key=template.key,
                scheduled_for=timezone.now(),
                context={
                    "room_id": room.pk,
                    "room_title": room.title,
                    "paid_until": str(room.paid_until),
                    "cta_url": _inbox_link(),
                },
            )

@shared_task(name="notifications.tasks.send_due_notifications")
def send_due_notifications() -> dict:
    """
    Deliver all due notifications using the single NotificationService pipeline.
    """
    from notifications.services import NotificationService

    now = timezone.now()

    qs = (
        OutboundNotification.objects.select_related("user")
        .filter(scheduled_for__lte=now, channel=NotificationTemplate.CHANNEL_EMAIL)
        .exclude(
            status__in=[
                OutboundNotification.STATUS_SENT,
                OutboundNotification.STATUS_SKIPPED,
            ]
        )
    )

    found = qs.count()
    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for notif in qs:
        NotificationService.deliver(notif)
        notif.refresh_from_db()

        if notif.status == OutboundNotification.STATUS_SENT:
            sent_count += 1
        elif notif.status == OutboundNotification.STATUS_SKIPPED:
            skipped_count += 1
        elif notif.status == OutboundNotification.STATUS_FAILED:
            failed_count += 1

    return {
        "sent": sent_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "found": found,
    }
    
    
@shared_task
def notify_completed_viewings(hours_back: int = 24) -> int:
    """
    Send the post-viewing notification 10 minutes after the selected
    viewing start time.

    Temporary staging/testing rule:
    - Viewing starts at 08:00
    - Post-viewing notification becomes eligible at 08:10

    Creates only once per booking:
      1) in-app notification
      2) queued booking.completed email
    """
    now = timezone.now()
    completion_delay = timedelta(minutes=10)

    # A booking becomes eligible when:
    # booking.start + 10 minutes <= now
    start_cutoff = now - completion_delay
    window_start = start_cutoff - timedelta(hours=hours_back)

    qs = (
        Booking.objects
        .filter(is_deleted=False, canceled_at__isnull=True)
        .filter(start__gte=window_start, start__lte=start_cutoff)
        .select_related("user", "room")
    )

    template = (
        NotificationTemplate.objects.filter(
            key="booking.completed",
            is_active=True,
            channel=NotificationTemplate.CHANNEL_EMAIL,
        ).first()
    )

    processed = 0

    for booking in qs:
        user = getattr(booking, "user", None)
        if not user:
            continue

        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not getattr(profile, "notify_confirmations", True):
            continue

        room = getattr(booking, "room", None)
        room_title = getattr(room, "title", "your room")

        start_local = timezone.localtime(booking.start)
        start_str = start_local.strftime("%d %b %Y, %H:%M")

        title = "Viewing completed"
        body = (
            f"Your viewing for '{room_title}' was scheduled for "
            f"{start_str}. (booking_id={booking.id})"
        )


        timer_one_created = False
        # ---------- 1) IN-APP (dedupe by booking_id) ----------
        already_in_app = Notification.objects.filter(
            user=user,
            type="booking_completed",
            body__icontains=f"(booking_id={booking.id})",
        ).exists()

        if not already_in_app:
            create_in_app_notification_if_allowed(
                user=user,
                notification_type="booking_completed",
                title=title,
                body=body,
                preference_field="notify_confirmations",
            )
            timer_one_created = True

        # ---------- 2) EMAIL QUEUE (dedupe by booking_id) ----------
        if template:
            already_queued = OutboundNotification.objects.filter(
                user=user,
                template_key="booking.completed",
                channel=NotificationTemplate.CHANNEL_EMAIL,
                context__booking_id=booking.id,
            ).exists()

            if not already_queued:
                OutboundNotification.objects.create(
                    user=user,
                    channel=NotificationTemplate.CHANNEL_EMAIL,
                    template_key="booking.completed",
                    scheduled_for=now,
                    context={
                        "user": {
                            "first_name": user.first_name,
                        },
                        "booking_id": booking.id,
                        "room_title": room_title,
                        "ended_at": start_str,
                        "cta_url": f"{_frontend_base_url()}/viewings/{booking.id}",
                    },
                )
                timer_one_created = True


                
        processed += 1

    return processed


     