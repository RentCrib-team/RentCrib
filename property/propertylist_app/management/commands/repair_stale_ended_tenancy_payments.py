from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import DateTimeField, F, OuterRef, Subquery
from django.utils import timezone

from propertylist_app.models import Payment, Room, Tenancy


class Command(BaseCommand):
    help = (
        "Expire stale room payment entitlement when the latest ended tenancy "
        "is newer than the latest successful payment."
    )

    def handle(self, *args, **options):
        latest_ended = (
            Tenancy.objects.filter(
                room_id=OuterRef("pk"),
                status=Tenancy.STATUS_ENDED,
            )
            .order_by("-updated_at")
            .values("updated_at")[:1]
        )
        latest_payment = (
            Payment.objects.filter(
                room_id=OuterRef("pk"),
                status=Payment.Status.SUCCEEDED,
            )
            .order_by("-created_at")
            .values("created_at")[:1]
        )

        today = timezone.localdate()
        stale_rooms = (
            Room.objects.annotate(
                latest_ended_at=Subquery(
                    latest_ended,
                    output_field=DateTimeField(),
                ),
                latest_paid_at=Subquery(
                    latest_payment,
                    output_field=DateTimeField(),
                ),
            )
            .filter(
                paid_until__gte=today,
                latest_ended_at__isnull=False,
                latest_paid_at__isnull=False,
                latest_ended_at__gt=F("latest_paid_at"),
            )
            .order_by("pk")
        )

        stale_ids = list(stale_rooms.values_list("pk", flat=True))
        if not stale_ids:
            self.stdout.write("No stale ended-tenancy payment entitlements found.")
            return

        expired_until = today - timedelta(days=1)
        updated = Room.objects.filter(pk__in=stale_ids).update(
            paid_until=expired_until,
            relisted_at=None,
            updated_at=timezone.now(),
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Expired stale payment entitlement for {updated} room(s): "
                + ", ".join(str(room_id) for room_id in stale_ids)
            )
        )
