from datetime import date, timedelta

import pytest
from django.utils import timezone

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Notification, Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def test_existing_ending_reminder_bell_repairs_missing_email_without_duplicate(
    user_factory,
    room_factory,
):
    NotificationTemplate.objects.create(
        key="tenancy.still_living_check_landlord",
        channel=NotificationTemplate.CHANNEL_EMAIL,
        subject="Tenancy ending soon",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = user_factory(
        username="ending_recovery_landlord",
        role="landlord",
    )
    tenant = user_factory(
        username="ending_recovery_tenant",
        role="seeker",
    )
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=30),
        duration_months=1,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(minutes=30),
        tenant_confirmed_at=now - timedelta(minutes=30),
        still_living_check_at=now - timedelta(minutes=1),
        still_living_landlord_confirmed_at=None,
        still_living_tenant_confirmed_at=now,
        still_living_confirmed_at=None,
    )

    Notification.objects.create(
        user=landlord,
        type="tenancy_still_living_check",
        target_type="still_living_check",
        target_id=tenancy.id,
        title="Your tenancy is ending soon",
        body="Existing bell from the first sweep",
    )

    bell_qs = Notification.objects.filter(
        user=landlord,
        type="tenancy_still_living_check",
        target_type="still_living_check",
        target_id=tenancy.id,
    )
    email_qs = OutboundNotification.objects.filter(
        user=landlord,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key="tenancy.still_living_check_landlord",
        context__tenancy_id=tenancy.id,
    )

    assert bell_qs.count() == 1
    assert email_qs.count() == 0

    task_tenancy_prompts_sweep()

    assert bell_qs.count() == 1
    assert email_qs.count() == 1

    # A later sweep must not duplicate either delivery once recovery succeeds.
    task_tenancy_prompts_sweep()

    assert bell_qs.count() == 1
    assert email_qs.count() == 1
