import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.api.views.common import ok_response
from propertylist_app.api.views.payments import _stripe_mod
from propertylist_app.models import Notification, Payment, Room, WebhookReceipt
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.listing_entitlements import (
    grant_complimentary_listing_benefit,
)
from propertylist_app.services.realtime import push_user_realtime_event


logger = logging.getLogger("rentout.webhooks")

SUCCESS_EVENT_TYPES = {
    "checkout.session.completed",
    "payment_intent.succeeded",
}


def _best_effort_payment_notifications(payment, room):
    payment_notification = None

    try:
        payment_notification = Notification.objects.create(
            user=payment.user,
            type="confirmation",
            title="Payment confirmed",
            body="Your listing payment was successful.",
            target_type="payment",
            target_id=payment.id,
            audience=Notification.Audience.LANDLORD,
        )
    except Exception:
        logger.exception(
            "stripe_webhook_payment_notification_create_failed payment_id=%s",
            payment.id,
        )

    if payment_notification is not None:
        try:
            push_user_realtime_event(
                payment.user.id,
                "new_notification",
                {
                    "kind": "payment_confirmed",
                    "notification_id": payment_notification.id,
                    "target_type": "payment",
                    "target_id": payment.id,
                },
            )
        except Exception:
            logger.exception(
                "stripe_webhook_payment_realtime_failed payment_id=%s",
                payment.id,
            )

    try:
        template_exists = NotificationTemplate.objects.filter(
            key="payment.confirmed",
            channel=NotificationTemplate.CHANNEL_EMAIL,
            is_active=True,
        ).exists()

        if template_exists:
            OutboundNotification.objects.create(
                user=payment.user,
                channel=NotificationTemplate.CHANNEL_EMAIL,
                template_key="payment.confirmed",
                scheduled_for=timezone.now(),
                context={
                    "user": {
                        "first_name": payment.user.first_name,
                    },
                    "room": {
                        "title": (
                            room.title
                            if room
                            else "your RentCrib listing"
                        ),
                    },
                    "payment_id": payment.id,
                    "cta_url": build_absolute_url(
                        "/my-listings",
                        force_login=True,
                    ),
                },
            )
    except Exception:
        logger.exception(
            "stripe_webhook_payment_email_enqueue_failed payment_id=%s",
            payment.id,
        )


def _mark_receipt_processed(receipt):
    if receipt is None:
        return

    receipt.processed = True
    receipt.processed_at = timezone.now()
    receipt.save(update_fields=["processed", "processed_at"])


def _create_webhook_receipt(request, event, data_obj):
    event_id = event.get("id") or ""
    if not event_id:
        return None

    metadata = data_obj.get("metadata") or {}
    evt_type = event.get("type")

    payment_intent = (
        data_obj.get("id")
        if evt_type == "payment_intent.succeeded"
        else data_obj.get("payment_intent")
    )

    try:
        receipt, _ = WebhookReceipt.objects.get_or_create(
            source="stripe",
            event_id=event_id,
            defaults={
                "payload": {
                    "id": event_id,
                    "type": evt_type,
                    "created": event.get("created"),
                    "livemode": event.get("livemode"),
                    "object": {
                        "id": data_obj.get("id"),
                        "payment_intent": payment_intent,
                        "metadata": metadata,
                    },
                },
                "headers": {
                    "Stripe-Signature": request.META.get(
                        "HTTP_STRIPE_SIGNATURE",
                        "",
                    ),
                    "User-Agent": request.META.get("HTTP_USER_AGENT", ""),
                    "Content-Type": request.META.get("CONTENT_TYPE", ""),
                },
            },
        )
        return receipt
    except Exception:
        logger.exception(
            "stripe_webhook_receipt_create_failed event_id=%s",
            event_id,
        )
        return None


def _payment_intent_id_for_event(evt_type, data_obj):
    if evt_type == "payment_intent.succeeded":
        return data_obj.get("id")

    return data_obj.get("payment_intent")


def _successful_payment_response(
    *,
    event,
    receipt,
    payment,
    payment_intent_id,
):
    event_id = event.get("id") or ""
    evt_type = event.get("type")
    room = payment.room
    updated = 0

    try:
        with transaction.atomic():
            updated = (
                Payment.objects
                .filter(id=payment.id)
                .exclude(status=Payment.Status.SUCCEEDED)
                .update(
                    status=Payment.Status.SUCCEEDED,
                    stripe_payment_intent_id=str(payment_intent_id or ""),
                )
            )

            if updated == 1:
                payment.refresh_from_db(
                    fields=["status", "stripe_payment_intent_id"]
                )

                if room:
                    today = timezone.localdate()
                    base = (
                        room.paid_until
                        if room.paid_until and room.paid_until > today
                        else today
                    )
                    room.paid_until = base + timedelta(days=30)
                    room.set_status(Room.Lifecycle.ACTIVE)
                    room.save(update_fields=["status", "paid_until"])

                grant_complimentary_listing_benefit(payment)
    except Exception:
        logger.exception(
            "stripe_webhook_payment_success_failed "
            "event_id=%s event_type=%s payment_id=%s",
            event_id,
            evt_type,
            payment.id,
        )
        return Response(
            {
                "ok": False,
                "message": "Unable to process payment.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if updated == 1:
        _best_effort_payment_notifications(payment, room)

    _mark_receipt_processed(receipt)

    return ok_response(
        {
            "detail": f"{evt_type} processed",
            "event_id": event_id,
            "event_type": evt_type,
            "payment_id": str(payment.id),
        },
        status_code=status.HTTP_200_OK,
    )


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def stripe_webhook_reliable(request):
    """
    Single Stripe webhook processor for both clients.

    Web Checkout sends checkout.session.completed.
    Native mobile PaymentSheet sends payment_intent.succeeded.
    Both events use the same validation and payment-success code path.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = _stripe_mod().Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except Exception:
        logger.warning("stripe_webhook_signature_failed")
        return Response(
            {
                "ok": False,
                "message": "Invalid payload or invalid Stripe signature.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    event_id = event.get("id") or ""
    evt_type = event.get("type")
    data_obj = (event.get("data") or {}).get("object") or {}
    metadata = data_obj.get("metadata") or {}

    logger.info(
        "stripe_webhook_received event_id=%s type=%s",
        event_id,
        evt_type,
    )

    receipt = _create_webhook_receipt(request, event, data_obj)

    if receipt and receipt.processed:
        return ok_response(
            {
                "detail": "already processed",
                "event_id": event_id,
                "event_type": evt_type,
            },
            status_code=status.HTTP_200_OK,
        )

    if evt_type == "checkout.session.expired":
        payment_id = metadata.get("payment_id")

        if payment_id:
            updated = (
                Payment.objects
                .filter(
                    id=payment_id,
                    status=Payment.Status.CREATED,
                )
                .update(status=Payment.Status.CANCELED)
            )

            if updated == 1:
                logger.info(
                    "stripe_webhook_session_expired payment_id=%s",
                    payment_id,
                )

        _mark_receipt_processed(receipt)

        return ok_response(
            {
                "detail": "checkout.session.expired processed",
                "event_id": event_id,
                "event_type": evt_type,
                "payment_id": str(payment_id) if payment_id else None,
            },
            status_code=status.HTTP_200_OK,
        )

    if evt_type not in SUCCESS_EVENT_TYPES:
        return ok_response(
            {
                "detail": f"ignored event {evt_type}",
                "event_id": event_id,
                "event_type": evt_type,
            },
            status_code=status.HTTP_200_OK,
        )

    payment_id = metadata.get("payment_id")
    room_id = metadata.get("room_id")
    user_id = metadata.get("user_id")

    if not payment_id:
        logger.warning(
            "stripe_webhook_missing_payment_metadata event_id=%s",
            event_id,
        )
        return Response(
            {
                "ok": False,
                "message": "Missing payment metadata.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        payment = Payment.objects.select_related("room", "user").get(
            id=payment_id
        )
    except Payment.DoesNotExist:
        logger.warning(
            "stripe_webhook_invalid_payment_id "
            "event_id=%s payment_id=%s",
            event_id,
            payment_id,
        )
        return Response(
            {
                "ok": False,
                "message": "Invalid payment metadata.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if user_id and str(payment.user_id) != str(user_id):
        logger.warning(
            "stripe_webhook_user_mismatch "
            "event_id=%s payment_id=%s "
            "metadata_user_id=%s actual_user_id=%s",
            event_id,
            payment_id,
            user_id,
            payment.user_id,
        )
        return Response(
            {
                "ok": False,
                "message": "Webhook metadata user mismatch.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if room_id and str(payment.room_id or "") != str(room_id):
        logger.warning(
            "stripe_webhook_room_mismatch "
            "event_id=%s payment_id=%s "
            "metadata_room_id=%s actual_room_id=%s",
            event_id,
            payment_id,
            room_id,
            payment.room_id,
        )
        return Response(
            {
                "ok": False,
                "message": "Webhook metadata room mismatch.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    return _successful_payment_response(
        event=event,
        receipt=receipt,
        payment=payment,
        payment_intent_id=_payment_intent_id_for_event(
            evt_type,
            data_obj,
        ),
    )
