# propertylist_app/tests/tenancies/test_tenancy_extension_endpoints.py

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

import pytest
from django.utils import timezone
from notifications.models import (
    NotificationTemplate,
    OutboundNotification,
)
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

# Reason: Your API is versioned; using /api/v1 avoids 308 redirects from /api -> /api/v1
API_BASE = "/api/v1"


def _get_model(app_label: str, model_name: str):
    return __import__("django.apps").apps.apps.get_model(app_label, model_name)


def _make_booking(user, room, *, days_ago: int = 2):
    Booking = _get_model("propertylist_app", "Booking")

    end = timezone.now() - timedelta(days=days_ago)
    start = end - timedelta(minutes=30)

    return Booking.objects.create(
        user=user,
        room=room,
        start=start,
        end=end,
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )


def _make_tenancy(room, landlord, tenant, *, proposed_by, status, move_in_days_ago=90, duration_months=3):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    now = timezone.now()
    move_in = date.today() - timedelta(days=move_in_days_ago)

    return Tenancy.objects.create(
    room=room,
    landlord=landlord,
    tenant=tenant,
    proposed_by=proposed_by,
    move_in_date=move_in,
    duration_months=duration_months,
    status=status,
    landlord_confirmed_at=now - timedelta(days=move_in_days_ago),
    tenant_confirmed_at=now - timedelta(days=move_in_days_ago),

    # Test fixture: place tenancy inside the QA update window.
    still_living_check_at=now - timedelta(minutes=1),
    review_open_at=now + timedelta(minutes=9),
    )


def _auth(client: APIClient, user):
    client.force_authenticate(user=user)
    
def _renewal_start_date(*, days_from_today: int = 1):
    return date.today() + timedelta(
        days=days_from_today,
    )    
    
def _create_extension_email_templates():
    templates = (
        (
            "tenancy.extension.proposed",
            "Tenancy renewal proposed",
        ),
        (
            "tenancy.extension.accepted",
            "Tenancy renewal accepted",
        ),
        (
            "tenancy.extension.rejected",
            "Tenancy renewal declined",
        ),
    )

    for key, subject in templates:
        NotificationTemplate.objects.get_or_create(
            key=key,
            channel="email",
            defaults={
                "subject": subject,
                "body": (
                    "{{ proposed_start_date }} "
                    "{{ proposed_duration_months }} "
                    "{{ cta_url }}"
                ),
                "is_active": True,
            },
        )
    
    
    
    


def test_extension_create_by_landlord_creates_proposal(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord1")
    tenant = user_factory(username="ex_tenant1")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    _auth(client, landlord)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    renewal_start_date = _renewal_start_date()

    res = client.post(
        url,
        data={
            "proposed_start_date": str(
                renewal_start_date
            ),
            "proposed_duration_months": 6,
        },
        format="json",
    )

    assert res.status_code == 201
    extension = TenancyExtension.objects.get(
    tenancy=tenancy,
    status=TenancyExtension.STATUS_PROPOSED,
)

    assert (
        extension.proposed_start_date
        == renewal_start_date
    )
    assert extension.proposed_duration_months == 6


def test_extension_create_by_tenant_creates_proposal(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord2")
    tenant = user_factory(username="ex_tenant2")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    _auth(client, tenant)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    renewal_start_date = _renewal_start_date()

    res = client.post(
        url,
        data={
            "proposed_start_date": str(
                renewal_start_date
            ),
            "proposed_duration_months": 9,
        },
        format="json",
    )

    assert res.status_code == 201
    extension = TenancyExtension.objects.get(
    tenancy=tenancy,
    status=TenancyExtension.STATUS_PROPOSED,
    )

    assert (
        extension.proposed_start_date
        == renewal_start_date
    )
    assert extension.proposed_duration_months == 9


def test_extension_create_forbidden_for_non_party(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="ex_landlord3")
    tenant = user_factory(username="ex_tenant3")
    outsider = user_factory(username="ex_outsider3")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    client = APIClient()
    _auth(client, outsider)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(
        url,
        data={
            "proposed_start_date": str(
                _renewal_start_date()
            ),
            "proposed_duration_months": 6,
        },
        format="json",
    )

    assert res.status_code == 403


def test_extension_respond_accept_updates_tenancy(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )

    landlord = user_factory(
        username="ex_landlord4",
    )
    tenant = user_factory(
        username="ex_tenant4",
    )
    room = room_factory(
        property_owner=landlord,
    )

    _make_booking(
        tenant,
        room,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=3,
    )
    renewal_start_date = _renewal_start_date(
        days_from_today=1,
    )
    renewal_duration_months = 7
    previous_review_open_at = (
        timezone.now() + timedelta(minutes=2)
    )
    previous_review_deadline_at = (
        timezone.now() + timedelta(days=30)
    )
    previous_still_living_check_at = (
        timezone.now() - timedelta(minutes=1)
    )

    tenancy.review_open_at = (
        previous_review_open_at
    )
    tenancy.review_deadline_at = (
        previous_review_deadline_at
    )
    tenancy.still_living_check_at = (
        previous_still_living_check_at
    )
    tenancy.still_living_confirmed_at = (
        timezone.now()
    )
    tenancy.still_living_landlord_confirmed_at = (
        timezone.now()
    )
    tenancy.still_living_tenant_confirmed_at = (
        timezone.now()
    )

    tenancy.save(
        update_fields=[
            "review_open_at",
            "review_deadline_at",
            "still_living_check_at",
            "still_living_confirmed_at",
            "still_living_landlord_confirmed_at",
            "still_living_tenant_confirmed_at",
        ]
    )

    room.is_available = True
    room.save(
        update_fields=[
            "is_available",
        ]
    )

    ext = TenancyExtension.objects.create(
    tenancy=tenancy,
    proposed_by=landlord,
    proposed_start_date=renewal_start_date,
    proposed_duration_months=(
        renewal_duration_months
    ),
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(
        client,
        tenant,
    )

    url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
        f"{ext.id}/respond/"
    )


    accepted_at_lower_bound = timezone.now()
    
    
    res = client.patch(
        url,
        data={
            "action": "accept",
        },
        format="json",
    )
    
    accepted_at_upper_bound = timezone.now()

    assert res.status_code == 200, res.data

    tenancy.refresh_from_db()
    room.refresh_from_db()
    ext.refresh_from_db()

    assert (
    tenancy.move_in_date
    == renewal_start_date
    )
    assert (
        tenancy.duration_months
        == renewal_duration_months
    )
    assert tenancy.status == Tenancy.STATUS_CONFIRMED

    assert (
        tenancy.review_open_at
        != previous_review_open_at
    )
    assert (
        tenancy.review_deadline_at
        != previous_review_deadline_at
    )
    assert (
        tenancy.still_living_check_at
        != previous_still_living_check_at
    )

    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None
    assert tenancy.still_living_check_at is not None
    
    expected_lower_bound = (
        accepted_at_lower_bound
        + timedelta(minutes=10)
    )
    expected_upper_bound = (
        accepted_at_upper_bound
        + timedelta(minutes=10)
    )

    assert (
        tenancy.still_living_check_at
        >= expected_lower_bound
    )
    assert (
        tenancy.still_living_check_at
        <= expected_upper_bound
    )
    

    assert tenancy.still_living_confirmed_at is None
    assert (
        tenancy.still_living_landlord_confirmed_at
        is None
    )
    assert (
        tenancy.still_living_tenant_confirmed_at
        is None
    )

    assert room.is_available is False

    assert (
        ext.status
        == TenancyExtension.STATUS_ACCEPTED
    )
    assert ext.responded_at is not None

def test_extension_respond_reject_leaves_tenancy_unchanged(
    user_factory,
    room_factory,
    ):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )

    landlord = user_factory(
        username="ex_landlord5",
    )
    tenant = user_factory(
        username="ex_tenant5",
    )
    room = room_factory(
        property_owner=landlord,
    )

    _make_booking(
        tenant,
        room,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=3,
    )

    original_move_in_date = tenancy.move_in_date
    original_duration_months = tenancy.duration_months
    original_status = tenancy.status
    original_review_open_at = tenancy.review_open_at
    original_review_deadline_at = (
        tenancy.review_deadline_at
    )
    original_still_living_check_at = (
        tenancy.still_living_check_at
    )

    proposed_start_date = _renewal_start_date()

    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=proposed_start_date,
        proposed_duration_months=10,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(
        client,
        tenant,
    )

    url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
        f"{ext.id}/respond/"
    )

    res = client.patch(
        url,
        data={
            "action": "reject",
        },
        format="json",
    )

    assert res.status_code == 200, res.data

    tenancy.refresh_from_db()
    ext.refresh_from_db()

    # Rejecting the renewal must leave the existing tenancy unchanged.
    assert (
        tenancy.move_in_date
        == original_move_in_date
    )
    assert (
        tenancy.duration_months
        == original_duration_months
    )
    assert tenancy.status == original_status
    assert (
        tenancy.review_open_at
        == original_review_open_at
    )
    assert (
        tenancy.review_deadline_at
        == original_review_deadline_at
    )
    assert (
        tenancy.still_living_check_at
        == original_still_living_check_at
    )

    # Only the extension proposal changes state.
    assert (
        ext.proposed_start_date
        == proposed_start_date
    )
    assert ext.proposed_duration_months == 10
    assert (
        ext.status
        == TenancyExtension.STATUS_REJECTED
    )
    assert ext.responded_at is not None

def test_extension_respond_forbidden_for_proposer(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord6")
    tenant = user_factory(username="ex_tenant6")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    ext = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=_renewal_start_date(),
        proposed_duration_months=8,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(client, landlord)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/{ext.id}/respond/"
    res = client.patch(url, data={"action": "accept"}, format="json")

    assert res.status_code == 403


def test_extension_prevents_multiple_open_proposals(user_factory, room_factory):
    Tenancy = _get_model("propertylist_app", "Tenancy")
    TenancyExtension = _get_model("propertylist_app", "TenancyExtension")

    landlord = user_factory(username="ex_landlord7")
    tenant = user_factory(username="ex_tenant7")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ACTIVE)

    TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=_renewal_start_date(),
        proposed_duration_months=6,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    client = APIClient()
    _auth(client, tenant)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(
        url,
        data={
            "proposed_start_date": str(
                _renewal_start_date(
                    days_from_today=2,
                )
            ),
            "proposed_duration_months": 9,
        },
        format="json",
    )

    assert res.status_code == 400


def test_extension_allowed_when_tenancy_ended_but_inside_grace_window(
    user_factory,
    room_factory,
):
    Tenancy = _get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="ex_landlord8")
    tenant = user_factory(username="ex_tenant8")
    room = room_factory(property_owner=landlord)
    _make_booking(tenant, room)

    tenancy = _make_tenancy(room=room, landlord=landlord, tenant=tenant, proposed_by=landlord, status=Tenancy.STATUS_ENDED)

    client = APIClient()
    _auth(client, landlord)

    url = f"{API_BASE}/tenancies/{tenancy.id}/extensions/"
    res = client.post(
        url,
        data={
            "proposed_start_date": str(
                _renewal_start_date()
            ),
            "proposed_duration_months": 6,
        },
        format="json",
    )

    assert res.status_code == 201, res.data
    
def test_multiple_consecutive_extensions_restart_lifecycle_each_time(
    user_factory,
    room_factory,
    ):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )

    landlord = user_factory(
        username="ex_landlord_multiple_renewals",
    )
    tenant = user_factory(
        username="ex_tenant_multiple_renewals",
    )
    room = room_factory(
        property_owner=landlord,
    )

    _make_booking(
        tenant,
        room,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=3,
    )

    room.is_available = False
    room.save(
        update_fields=[
            "is_available",
        ]
    )

    landlord_client = APIClient()
    tenant_client = APIClient()

    _auth(
        landlord_client,
        landlord,
    )
    _auth(
        tenant_client,
        tenant,
    )

    # -------------------------------------------------
    # First renewal period
    # -------------------------------------------------
    first_renewal_start = _renewal_start_date(
        days_from_today=1,
    )
    first_renewal_duration = 7

    first_create_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
    )

    first_create_response = landlord_client.post(
        first_create_url,
        data={
            "proposed_start_date": str(
                first_renewal_start
            ),
            "proposed_duration_months": (
                first_renewal_duration
            ),
        },
        format="json",
    )

    assert first_create_response.status_code == 201, (
        first_create_response.data
    )

    first_payload = first_create_response.data.get(
        "data",
        first_create_response.data,
    )

    first_extension = TenancyExtension.objects.get(
        id=first_payload["id"],
    )

    assert (
        first_extension.proposed_start_date
        == first_renewal_start
    )
    assert (
        first_extension.proposed_duration_months
        == first_renewal_duration
    )

    first_respond_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
        f"{first_extension.id}/respond/"
    )

    first_accept_response = tenant_client.patch(
        first_respond_url,
        data={
            "action": "accept",
        },
        format="json",
    )

    assert first_accept_response.status_code == 200, (
        first_accept_response.data
    )

    tenancy.refresh_from_db()
    first_extension.refresh_from_db()
    room.refresh_from_db()

    assert (
        tenancy.move_in_date
        == first_renewal_start
    )
    assert (
        tenancy.duration_months
        == first_renewal_duration
    )
    assert tenancy.status == Tenancy.STATUS_CONFIRMED
    assert room.is_available is False

    assert (
        first_extension.status
        == TenancyExtension.STATUS_ACCEPTED
    )
    assert first_extension.responded_at is not None

    first_review_open_at = tenancy.review_open_at
    first_review_deadline_at = (
        tenancy.review_deadline_at
    )
    first_still_living_check_at = (
        tenancy.still_living_check_at
    )

    assert first_review_open_at is not None
    assert first_review_deadline_at is not None
    assert first_still_living_check_at is not None

    tenancy.still_living_confirmed_at = (
        timezone.now()
    )
    tenancy.still_living_landlord_confirmed_at = (
        timezone.now()
    )
    tenancy.still_living_tenant_confirmed_at = (
        timezone.now()
    )

    tenancy.save(
        update_fields=[
            "still_living_confirmed_at",
            "still_living_landlord_confirmed_at",
            "still_living_tenant_confirmed_at",
        ]
    )

    # -------------------------------------------------
    # Second renewal period
    # -------------------------------------------------
    second_renewal_start = (
        first_renewal_start
        + relativedelta(
            months=first_renewal_duration,
        )
    )
    second_renewal_duration = 8


        # Simulate the renewed tenancy reaching its next QA update window.
    now = timezone.now()

    tenancy.still_living_check_at = (
        now - timedelta(minutes=1)
    )
    tenancy.review_open_at = (
        now + timedelta(minutes=9)
    )

    tenancy.save(
        update_fields=[
            "still_living_check_at",
            "review_open_at",
        ]
    )
    
    
    
    
    second_create_response = tenant_client.post(
        first_create_url,
        data={
            "proposed_start_date": str(
                second_renewal_start
            ),
            "proposed_duration_months": (
                second_renewal_duration
            ),
        },
        format="json",
    )

    assert second_create_response.status_code == 201, (
        second_create_response.data
    )

    second_payload = second_create_response.data.get(
        "data",
        second_create_response.data,
    )

    second_extension = TenancyExtension.objects.get(
        id=second_payload["id"],
    )

    assert (
        second_extension.id
        != first_extension.id
    )
    assert (
        second_extension.proposed_by_id
        == tenant.id
    )
    assert (
        second_extension.proposed_start_date
        == second_renewal_start
    )
    assert (
        second_extension.proposed_duration_months
        == second_renewal_duration
    )
    assert (
        second_extension.status
        == TenancyExtension.STATUS_PROPOSED
    )

    second_respond_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
        f"{second_extension.id}/respond/"
    )

    second_accept_response = landlord_client.patch(
        second_respond_url,
        data={
            "action": "accept",
        },
        format="json",
    )

    assert second_accept_response.status_code == 200, (
        second_accept_response.data
    )

    tenancy.refresh_from_db()
    first_extension.refresh_from_db()
    second_extension.refresh_from_db()
    room.refresh_from_db()

    assert (
        tenancy.move_in_date
        == second_renewal_start
    )
    assert (
        tenancy.duration_months
        == second_renewal_duration
    )
    assert tenancy.status == Tenancy.STATUS_CONFIRMED

    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None
    assert tenancy.still_living_check_at is not None

    assert (
        tenancy.review_open_at
        > first_review_open_at
    )
    assert (
        tenancy.review_deadline_at
        > first_review_deadline_at
    )
    assert (
        tenancy.still_living_check_at
        > first_still_living_check_at
    )

    assert tenancy.still_living_confirmed_at is None
    assert (
        tenancy.still_living_landlord_confirmed_at
        is None
    )
    assert (
        tenancy.still_living_tenant_confirmed_at
        is None
    )

    assert room.is_available is False

    assert (
        first_extension.status
        == TenancyExtension.STATUS_ACCEPTED
    )
    assert (
        second_extension.status
        == TenancyExtension.STATUS_ACCEPTED
    )

    assert (
        TenancyExtension.objects.filter(
            tenancy=tenancy,
            status=TenancyExtension.STATUS_ACCEPTED,
        ).count()
        == 2
    )

    assert not TenancyExtension.objects.filter(
        tenancy=tenancy,
        status=TenancyExtension.STATUS_PROPOSED,
    ).exists()
    
    
def test_extension_create_endpoint_triggers_proposed_notifications(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    _create_extension_email_templates()

    landlord = user_factory(
        username="endpoint_notification_landlord",
        email="endpoint-landlord@example.com",
    )
    tenant = user_factory(
        username="endpoint_notification_tenant",
        email="endpoint-tenant@example.com",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=6,
    )

    client = APIClient()
    _auth(
        client,
        landlord,
    )

    renewal_start_date = _renewal_start_date(
        days_from_today=30,
    )

    url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
    )

    response = client.post(
        url,
        data={
            "proposed_start_date": str(
                renewal_start_date
            ),
            "proposed_duration_months": 7,
        },
        format="json",
    )

    assert response.status_code == 201, response.data

    payload = response.data.get(
        "data",
        response.data,
    )

    extension = TenancyExtension.objects.get(
        id=payload["id"],
    )

    inbox_notification = Notification.objects.get(
        user=tenant,
        type="tenancy_extension_proposed",
        target_type="tenancy_extension",
        target_id=extension.id,
    )

    assert (
        inbox_notification.title
        == "Tenancy renewal proposed"
    )
    assert room.title in inbox_notification.body
    assert "7 months" in inbox_notification.body

    email = OutboundNotification.objects.get(
        user=tenant,
        template_key="tenancy.extension.proposed",
        context__extension_id=extension.id,
    )

    assert (
        email.context["proposed_start_date"]
        == renewal_start_date.isoformat()
    )
    assert (
        email.context["proposed_duration_months"]
        == 7
    )

    proposer_notification = Notification.objects.get(
        user=landlord,
        type="tenancy_extension_proposed",
        target_type="tenancy_extension",
        target_id=extension.id,
    )

    assert (
        proposer_notification.title
        == "Tenancy renewal proposed"
    )

    assert room.title in proposer_notification.body

    assert "has been sent" in proposer_notification.body   
    
def test_extension_accept_endpoint_triggers_accepted_notifications(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    _create_extension_email_templates()

    landlord = user_factory(
        username="endpoint_accept_landlord",
        email="endpoint-accept-landlord@example.com",
    )
    tenant = user_factory(
        username="endpoint_accept_tenant",
        email="endpoint-accept-tenant@example.com",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=6,
    )

    landlord_client = APIClient()
    tenant_client = APIClient()

    _auth(
        landlord_client,
        landlord,
    )
    _auth(
        tenant_client,
        tenant,
    )

    renewal_start_date = _renewal_start_date(
        days_from_today=30,
    )

    create_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
    )

    create_response = landlord_client.post(
        create_url,
        data={
            "proposed_start_date": str(
                renewal_start_date
            ),
            "proposed_duration_months": 7,
        },
        format="json",
    )

    assert create_response.status_code == 201, (
        create_response.data
    )

    create_payload = create_response.data.get(
        "data",
        create_response.data,
    )

    extension = TenancyExtension.objects.get(
        id=create_payload["id"],
    )

    respond_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
        f"{extension.id}/respond/"
    )

    accept_response = tenant_client.patch(
        respond_url,
        data={
            "action": "accept",
        },
        format="json",
    )

    assert accept_response.status_code == 200, (
        accept_response.data
    )

    extension.refresh_from_db()

    assert (
        extension.status
        == TenancyExtension.STATUS_ACCEPTED
    )

    inbox_notifications = Notification.objects.filter(
        type="tenancy_extension_accepted",
        target_type="tenancy_extension",
        target_id=extension.id,
    )

    assert inbox_notifications.count() == 2

    assert set(
        inbox_notifications.values_list(
            "user_id",
            flat=True,
        )
    ) == {
        landlord.id,
        tenant.id,
    }

    accepted_emails = OutboundNotification.objects.filter(
        template_key="tenancy.extension.accepted",
        context__extension_id=extension.id,
    )

    assert accepted_emails.count() == 2

    assert set(
        accepted_emails.values_list(
            "user_id",
            flat=True,
        )
    ) == {
        landlord.id,
        tenant.id,
    }    
    
    
def test_extension_reject_endpoint_triggers_rejected_notifications(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    _create_extension_email_templates()

    landlord = user_factory(
        username="endpoint_reject_landlord",
        email="endpoint-reject-landlord@example.com",
    )
    tenant = user_factory(
        username="endpoint_reject_tenant",
        email="endpoint-reject-tenant@example.com",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=6,
    )

    landlord_client = APIClient()
    tenant_client = APIClient()

    _auth(
        landlord_client,
        landlord,
    )
    _auth(
        tenant_client,
        tenant,
    )

    renewal_start_date = _renewal_start_date(
        days_from_today=30,
    )

    create_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
    )

    create_response = tenant_client.post(
        create_url,
        data={
            "proposed_start_date": str(
                renewal_start_date
            ),
            "proposed_duration_months": 8,
        },
        format="json",
    )

    assert create_response.status_code == 201, (
        create_response.data
    )

    create_payload = create_response.data.get(
        "data",
        create_response.data,
    )

    extension = TenancyExtension.objects.get(
        id=create_payload["id"],
    )

    respond_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
        f"{extension.id}/respond/"
    )

    reject_response = landlord_client.patch(
        respond_url,
        data={
            "action": "reject",
        },
        format="json",
    )

    assert reject_response.status_code == 200, (
        reject_response.data
    )

    extension.refresh_from_db()

    assert (
        extension.status
        == TenancyExtension.STATUS_REJECTED
    )

    inbox_notification = Notification.objects.get(
        user=tenant,
        type="tenancy_extension_rejected",
        target_type="tenancy_extension",
        target_id=extension.id,
    )

    assert (
        inbox_notification.title
        == "Tenancy renewal declined"
    )
    assert "8 months" in inbox_notification.body

    email = OutboundNotification.objects.get(
        user=tenant,
        template_key="tenancy.extension.rejected",
        context__extension_id=extension.id,
    )

    assert (
        email.context["proposed_start_date"]
        == renewal_start_date.isoformat()
    )
    assert (
        email.context["proposed_duration_months"]
        == 8
    )

    assert not Notification.objects.filter(
        user=landlord,
        type="tenancy_extension_rejected",
        target_type="tenancy_extension",
        target_id=extension.id,
    ).exists()    
    
    
def test_accepted_renewal_triggers_timer_two_email_and_inbox_after_ten_minutes(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )
    Notification = _get_model(
        "propertylist_app",
        "Notification",
    )

    from propertylist_app.tasks import (
        task_tenancy_prompts_sweep,
    )

    NotificationTemplate.objects.get_or_create(
        key="tenancy.still_living_check",
        channel="email",
        defaults={
            "subject": "Your tenancy is ending soon",
            "body": (
                "{{ room_title }} "
                "{{ cta_url }}"
            ),
            "is_active": True,
        },
    )

    NotificationTemplate.objects.get_or_create(
        key="tenancy.still_living_check_landlord",
        channel="email",
        defaults={
            "subject": "Your tenancy is ending soon",
            "body": (
                "{{ room_title }} "
                "{{ cta_url }}"
            ),
            "is_active": True,
        },
    )

    landlord = user_factory(
        username="renewal_timer_landlord",
        email="renewal-timer-landlord@example.com",
    )
    tenant = user_factory(
        username="renewal_timer_tenant",
        email="renewal-timer-tenant@example.com",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=6,
    )

    renewal_start_date = _renewal_start_date(
        days_from_today=30,
    )

    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=renewal_start_date,
        proposed_duration_months=7,
        status=TenancyExtension.STATUS_PROPOSED,
    )

    tenant_client = APIClient()
    _auth(
        tenant_client,
        tenant,
    )

    respond_url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
        f"{extension.id}/respond/"
    )

    accepted_at_lower_bound = timezone.now()

    response = tenant_client.patch(
        respond_url,
        data={
            "action": "accept",
        },
        format="json",
    )

    accepted_at_upper_bound = timezone.now()

    assert response.status_code == 200, response.data

    tenancy.refresh_from_db()
    extension.refresh_from_db()

    assert (
        extension.status
        == TenancyExtension.STATUS_ACCEPTED
    )

    assert tenancy.still_living_check_at is not None

    assert (
        tenancy.still_living_check_at
        >= accepted_at_lower_bound
        + timedelta(minutes=10)
    )
    assert (
        tenancy.still_living_check_at
        <= accepted_at_upper_bound
        + timedelta(minutes=10)
    )

    # The ending reminder must not exist immediately.
    assert not Notification.objects.filter(
        type="tenancy_still_living_check",
        target_type="still_living_check",
        target_id=tenancy.id,
    ).exists()

    assert not OutboundNotification.objects.filter(
        template_key__in=[
            "tenancy.still_living_check",
            "tenancy.still_living_check_landlord",
        ],
        context__tenancy_id=tenancy.id,
    ).exists()

    # Simulate the ten-minute QA deadline becoming due.
    Tenancy.objects.filter(
        id=tenancy.id,
    ).update(
        still_living_check_at=(
            timezone.now() - timedelta(seconds=1)
        ),
        still_living_confirmed_at=None,
        still_living_landlord_confirmed_at=None,
        still_living_tenant_confirmed_at=None,
    )

    task_tenancy_prompts_sweep()

    inbox_notifications = Notification.objects.filter(
        type="tenancy_still_living_check",
        target_type="still_living_check",
        target_id=tenancy.id,
    )

    assert inbox_notifications.count() == 2

    assert set(
        inbox_notifications.values_list(
            "user_id",
            flat=True,
        )
    ) == {
        landlord.id,
        tenant.id,
    }

    landlord_email = OutboundNotification.objects.get(
        user=landlord,
        template_key=(
            "tenancy.still_living_check_landlord"
        ),
        context__tenancy_id=tenancy.id,
    )

    tenant_email = OutboundNotification.objects.get(
        user=tenant,
        template_key="tenancy.still_living_check",
        context__tenancy_id=tenancy.id,
    )

    assert (
        landlord_email.context["room_title"]
        == room.title
    )
    assert (
        tenant_email.context["room_title"]
        == room.title
    )

    # Re-running the sweep must not duplicate Timer 2.
    task_tenancy_prompts_sweep()

    assert Notification.objects.filter(
        type="tenancy_still_living_check",
        target_type="still_living_check",
        target_id=tenancy.id,
    ).count() == 2

    assert OutboundNotification.objects.filter(
        template_key__in=[
            "tenancy.still_living_check",
            "tenancy.still_living_check_landlord",
        ],
        context__tenancy_id=tenancy.id,
    ).count() == 2    
    
    
def test_extension_history_returns_all_renewals_oldest_first(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )
    TenancyExtension = _get_model(
        "propertylist_app",
        "TenancyExtension",
    )

    landlord = user_factory(
        username="history_landlord",
        first_name="History Landlord",
    )
    tenant = user_factory(
        username="history_tenant",
        first_name="History Tenant",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
        duration_months=6,
    )

    first_start_date = _renewal_start_date(
        days_from_today=30,
    )
    second_start_date = (
        first_start_date
        + relativedelta(months=7)
    )
    third_start_date = (
        second_start_date
        + relativedelta(months=8)
    )

    first_extension = (
        TenancyExtension.objects.create(
            tenancy=tenancy,
            proposed_by=landlord,
            proposed_start_date=first_start_date,
            proposed_duration_months=7,
            status=(
                TenancyExtension.STATUS_ACCEPTED
            ),
            responded_at=(
                timezone.now()
                - timedelta(days=20)
            ),
        )
    )

    second_extension = (
        TenancyExtension.objects.create(
            tenancy=tenancy,
            proposed_by=tenant,
            proposed_start_date=second_start_date,
            proposed_duration_months=8,
            status=(
                TenancyExtension.STATUS_REJECTED
            ),
            responded_at=(
                timezone.now()
                - timedelta(days=10)
            ),
        )
    )

    third_extension = (
        TenancyExtension.objects.create(
            tenancy=tenancy,
            proposed_by=landlord,
            proposed_start_date=third_start_date,
            proposed_duration_months=6,
            status=(
                TenancyExtension.STATUS_PROPOSED
            ),
        )
    )

    now = timezone.now()

    TenancyExtension.objects.filter(
        id=first_extension.id,
    ).update(
        created_at=now - timedelta(days=30),
    )
    TenancyExtension.objects.filter(
        id=second_extension.id,
    ).update(
        created_at=now - timedelta(days=20),
    )
    TenancyExtension.objects.filter(
        id=third_extension.id,
    ).update(
        created_at=now - timedelta(days=10),
    )

    landlord_client = APIClient()
    tenant_client = APIClient()

    _auth(
        landlord_client,
        landlord,
    )
    _auth(
        tenant_client,
        tenant,
    )

    url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
    )

    landlord_response = landlord_client.get(
        url,
    )
    tenant_response = tenant_client.get(
        url,
    )

    assert landlord_response.status_code == 200, (
        landlord_response.data
    )
    assert tenant_response.status_code == 200, (
        tenant_response.data
    )

    landlord_history = landlord_response.data[
        "data"
    ]
    tenant_history = tenant_response.data[
        "data"
    ]

    assert landlord_history == tenant_history
    assert len(landlord_history) == 3

    assert [
        item["id"]
        for item in landlord_history
    ] == [
        first_extension.id,
        second_extension.id,
        third_extension.id,
    ]

    first_item = landlord_history[0]
    second_item = landlord_history[1]
    third_item = landlord_history[2]

    assert (
        first_item["proposed_by_user_id"]
        == landlord.id
    )
    assert (
        first_item["proposed_by_role"]
        == "landlord"
    )
    assert (
        first_item["proposed_by_name"]
        == "History Landlord"
    )
    assert (
        first_item["proposed_start_date"]
        == first_start_date.isoformat()
    )
    assert (
        first_item["proposed_duration_months"]
        == 7
    )
    assert (
        first_item["status"]
        == TenancyExtension.STATUS_ACCEPTED
    )

    assert (
        second_item["proposed_by_user_id"]
        == tenant.id
    )
    assert (
        second_item["proposed_by_role"]
        == "tenant"
    )
    assert (
        second_item["status"]
        == TenancyExtension.STATUS_REJECTED
    )

    assert (
        third_item["status"]
        == TenancyExtension.STATUS_PROPOSED
    )
    assert third_item["responded_at"] is None  
    
def test_extension_history_returns_empty_list_when_none_exist(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )

    landlord = user_factory(
        username="empty_history_landlord",
    )
    tenant = user_factory(
        username="empty_history_tenant",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
    )

    client = APIClient()
    _auth(
        client,
        landlord,
    )

    url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
    )

    response = client.get(
        url,
    )

    assert response.status_code == 200, response.data
    assert response.data["data"] == []
    
def test_extension_history_forbidden_for_non_party(
    user_factory,
    room_factory,
):
    Tenancy = _get_model(
        "propertylist_app",
        "Tenancy",
    )

    landlord = user_factory(
        username="forbidden_history_landlord",
    )
    tenant = user_factory(
        username="forbidden_history_tenant",
    )
    outsider = user_factory(
        username="forbidden_history_outsider",
    )
    room = room_factory(
        property_owner=landlord,
    )

    tenancy = _make_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        status=Tenancy.STATUS_ACTIVE,
    )

    client = APIClient()
    _auth(
        client,
        outsider,
    )

    url = (
        f"{API_BASE}/tenancies/"
        f"{tenancy.id}/extensions/"
    )

    response = client.get(
        url,
    )

    assert response.status_code == 403
    
    
def test_extension_history_returns_404_for_missing_tenancy(
    user_factory,
):
    user = user_factory(
        username="missing_history_user",
    )

    client = APIClient()
    _auth(
        client,
        user,
    )

    response = client.get(
        f"{API_BASE}/tenancies/999999/extensions/",
    )

    assert response.status_code == 404              