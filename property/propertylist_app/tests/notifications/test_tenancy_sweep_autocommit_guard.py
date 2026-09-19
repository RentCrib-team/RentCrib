from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.models import Room, RoomCategorie, Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep


User = get_user_model()


@pytest.mark.django_db(transaction=True)
def test_still_living_sweep_can_save_existing_active_tenancy_in_autocommit():
    """Celery must process an existing active tenancy without an outer transaction."""
    NotificationTemplate.objects.create(
        key="tenancy.still_living_check",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )
    NotificationTemplate.objects.create(
        key="tenancy.still_living_check_landlord",
        channel="email",
        subject="x",
        body="Open: {{ cta_url }}",
        is_active=True,
    )

    landlord = User.objects.create_user(
        username="autocommit_guard_landlord",
        email="landlord@example.com",
        password="x",
    )
    tenant = User.objects.create_user(
        username="autocommit_guard_tenant",
        email="tenant@example.com",
        password="x",
    )
    category = RoomCategorie.objects.create(
        name="Autocommit guard category",
        active=True,
    )
    room = Room.objects.create(
        property_owner=landlord,
        title="Autocommit guard room",
        description="desc",
        price_per_month=600,
        location="SO14 1AA",
        category=category,
    )

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=30),
        duration_months=1,
        status=Tenancy.STATUS_PROPOSED,
    )

    # The ownership transition still uses the row-lock guard inside a real
    # transaction. The Celery sweep below deliberately runs after that
    # transaction has ended, matching the worker's normal autocommit mode.
    with transaction.atomic():
        tenancy.status = Tenancy.STATUS_ACTIVE
        tenancy.landlord_confirmed_at = timezone.now() - timedelta(days=30)
        tenancy.tenant_confirmed_at = timezone.now() - timedelta(days=30)
        tenancy.still_living_check_at = timezone.now() - timedelta(minutes=1)
        tenancy.save(
            update_fields=[
                "status",
                "landlord_confirmed_at",
                "tenant_confirmed_at",
                "still_living_check_at",
                "updated_at",
            ]
        )

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()
    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None

    assert OutboundNotification.objects.filter(
        user=landlord,
        template_key="tenancy.still_living_check_landlord",
    ).exists()
    assert OutboundNotification.objects.filter(
        user=tenant,
        template_key="tenancy.still_living_check",
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_live_ownership_transition_still_blocks_a_second_live_tenancy():
    """Skipping routine live saves must not weaken the ownership race guard."""
    landlord = User.objects.create_user(
        username="autocommit_guard_owner",
        email="owner@example.com",
        password="x",
    )
    tenant_a = User.objects.create_user(
        username="autocommit_guard_tenant_a",
        email="tenant-a@example.com",
        password="x",
    )
    tenant_b = User.objects.create_user(
        username="autocommit_guard_tenant_b",
        email="tenant-b@example.com",
        password="x",
    )
    category = RoomCategorie.objects.create(
        name="Ownership guard category",
        active=True,
    )
    room = Room.objects.create(
        property_owner=landlord,
        title="Autocommit guard ownership room",
        description="desc",
        price_per_month=650,
        location="SO14 1AB",
        category=category,
    )

    tenancy_a = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant_a,
        proposed_by=landlord,
        move_in_date=date.today(),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )
    tenancy_b = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant_b,
        proposed_by=landlord,
        move_in_date=date.today(),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )

    with transaction.atomic():
        tenancy_a.status = Tenancy.STATUS_ACTIVE
        tenancy_a.save(update_fields=["status", "updated_at"])

    with pytest.raises(ValidationError):
        with transaction.atomic():
            tenancy_b.status = Tenancy.STATUS_ACTIVE
            tenancy_b.save(update_fields=["status", "updated_at"])
