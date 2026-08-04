import pytest
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework.test import APIClient

from propertylist_app.models import RoomCategorie, Room, Booking

# IMPORTANT: once you add Tenancy model, this import must work
from propertylist_app.models import Tenancy


pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def _api_client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_user(username: str):
    User = get_user_model()
    return User.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(owner):
    cat = RoomCategorie.objects.create(name="Standard")
    return Room.objects.create(
        title="Nice room",
        description="Clean room",
        price_per_month="500.00",
        location="Southampton",
        category=cat,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        property_type="flat",
    )


def _make_viewing_booking(user, room):
    now = timezone.now()
    return Booking.objects.create(
        user=user,
        room=room,
        start=now - timedelta(days=2),
        end=now - timedelta(days=2, minutes=-30),  # 30 mins after start, still in the past
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )



def test_landlord_proposes_tenancy_creates_single_proposal_row():
    landlord = _make_user("landlord_a")
    tenant = _make_user("tenant_a")
    room = _make_room(owner=landlord)

    # viewing exists (relationship proof)
    _make_viewing_booking(user=tenant, room=room)

    client = _api_client_for(landlord)

    payload = {
        "room_id": room.id,
        "counterparty_user_id": tenant.id,
        "move_in_date": str(date.today() + timedelta(days=7)),
        "duration_months": 6,
    }

    resp = client.post(f"{API_PREFIX}/tenancies/propose/", data=payload, format="json")
    assert resp.status_code == 201, resp.data

    response_payload = resp.data.get("data", resp.data)
    tenancy_id = response_payload["id"]
    tenancy = Tenancy.objects.get(id=response_payload["id"])

    assert tenancy.room_id == room.id
    assert tenancy.landlord_id == landlord.id
    assert tenancy.tenant_id == tenant.id
    assert tenancy.proposed_by_id == landlord.id
    assert tenancy.status == Tenancy.STATUS_PROPOSED

    # landlord initiated, so landlord_confirmed_at should be set (as per our planned logic)
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is None
    # The landlord submitted the terms, so the landlord must wait.
    assert response_payload["can_agree"] is False
    assert response_payload["can_edit"] is False
    assert response_payload["available_actions"] == []

    # A second initial proposal must not overwrite the existing tenancy.
    resp2 = client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data=payload,
        format="json",
    )

    assert resp2.status_code == 400, resp2.data
    assert Tenancy.objects.filter(room=room, tenant=tenant).count() == 1

    tenancy.refresh_from_db()

    assert tenancy.proposed_by_id == landlord.id
    assert tenancy.move_in_date == date.today() + timedelta(days=7)
    assert tenancy.duration_months == 6
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is None


def test_tenant_can_propose_tenancy_when_landlord_is_busy():
    landlord = _make_user("landlord_b")
    tenant = _make_user("tenant_b")
    room = _make_room(owner=landlord)

    # viewing exists (relationship proof)
    _make_viewing_booking(user=tenant, room=room)

    client = _api_client_for(tenant)

    payload = {
        "room_id": room.id,
        "counterparty_user_id": landlord.id,  # tenant proposes to landlord (room owner)
        "move_in_date": str(date.today() + timedelta(days=10)),
        "duration_months": 3,
    }

    resp = client.post(f"{API_PREFIX}/tenancies/propose/", data=payload, format="json")
    assert resp.status_code == 201, resp.data

    payload = resp.data.get("data", resp.data)
    tenancy = Tenancy.objects.get(id=payload["id"])
    assert tenancy.landlord_id == landlord.id
    assert tenancy.tenant_id == tenant.id
    assert tenancy.proposed_by_id == tenant.id
    assert tenancy.status == Tenancy.STATUS_PROPOSED

    # tenant initiated; by design, tenant_confirmed_at set, landlord_confirmed_at None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.landlord_confirmed_at is None


def test_propose_changes_resets_confirmations_and_updates_dates():
    landlord = _make_user("landlord_c")
    tenant = _make_user("tenant_c")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    # landlord proposes
    resp = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    payload = resp.data.get("data", resp.data)
    tenancy_id = payload["id"]

    # Tenant proposes amended tenancy terms.
    resp2 = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(
                date.today() + timedelta(days=14)
            ),
            "duration_months": 12,
        },
        format="json",
    )
    
    assert resp2.status_code == 200, resp2.data

    tenancy = Tenancy.objects.get(id=tenancy_id)
    assert tenancy.proposed_by_id == tenant.id
    assert str(tenancy.move_in_date) == str(date.today() + timedelta(days=14))
    assert tenancy.duration_months == 12

  
    # The one-time correction becomes the final tenancy information.
    # No further Agree/Edit cycle is required.
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.tenant_has_edited is True
    assert tenancy.status == Tenancy.STATUS_CONFIRMED

    # Temporary QA rule: Timer 2 is scheduled after the correction.
    assert tenancy.still_living_check_at is not None
    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None
    
    
def test_landlord_can_edit_once_when_tenant_created_original_proposal():
    landlord = _make_user("landlord_landlord_edit")
    tenant = _make_user("tenant_landlord_edit")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    original_move_in_date = date.today() + timedelta(days=10)
    amended_move_in_date = date.today() + timedelta(days=14)

    # Tenant creates the original tenancy information.
    response = tenant_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(original_move_in_date),
            "duration_months": 3,
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    
    tenant_proposal_payload = response.data.get("data", response.data)

    # Tenant submitted the terms and must wait for the landlord.
    assert tenant_proposal_payload["can_agree"] is False
    assert tenant_proposal_payload["can_edit"] is False
    assert tenant_proposal_payload["available_actions"] == []

    response_payload = response.data.get("data", response.data)
    tenancy_id = response_payload["id"]

    # Landlord is the reviewing party and may edit once.
    edit_response = landlord_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(amended_move_in_date),
            "duration_months": 6,
        },
        format="json",
    )

    assert edit_response.status_code == 200, edit_response.data
    
    edit_payload = edit_response.data.get("data", edit_response.data)

    # The correction is now finalised immediately.
    assert edit_payload["can_agree"] is False
    assert edit_payload["can_edit"] is False
    assert edit_payload["available_actions"] == []

    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert tenancy.proposed_by_id == landlord.id
    assert tenancy.move_in_date == amended_move_in_date
    assert tenancy.duration_months == 6
    assert tenancy.tenant_has_edited is True

    # The one-time correction becomes the final tenancy information.
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.status == Tenancy.STATUS_CONFIRMED

    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None
    assert tenancy.still_living_check_at is not None  


def test_receiving_party_gets_agree_and_edit_actions():
    landlord = _make_user("landlord_actions")
    tenant = _make_user("tenant_actions")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    response = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert response.status_code == 201, response.data

    # Fetch the tenancy list as the receiving tenant.
    list_response = tenant_client.get(
    f"{API_PREFIX}/tenancies/mine/",
    )

    assert list_response.status_code == 200, getattr(
    list_response,
    "data",
    list_response.content,
)

    response_data = list_response.data.get("data", list_response.data)

    if isinstance(response_data, dict) and "results" in response_data:
        tenancies = response_data["results"]
    else:
        tenancies = response_data

    tenancy_payload = next(
        item
        for item in tenancies
        if item["room"] == room.id
    )

    assert tenancy_payload["can_agree"] is True
    assert tenancy_payload["can_edit"] is True
    assert tenancy_payload["available_actions"] == [
        "confirm",
        "propose_changes",
    ]




def test_original_proposer_cannot_edit_own_tenancy_information():
    landlord = _make_user("landlord_own_edit")
    tenant = _make_user("tenant_own_edit")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)

    response = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert response.status_code == 201, response.data

    response_payload = response.data.get("data", response.data)
    tenancy_id = response_payload["id"]

    edit_response = landlord_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(date.today() + timedelta(days=14)),
            "duration_months": 12,
        },
        format="json",
    )

    assert edit_response.status_code == 400, edit_response.data

    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert tenancy.proposed_by_id == landlord.id
    assert tenancy.move_in_date == date.today() + timedelta(days=7)
    assert tenancy.duration_months == 6
    assert tenancy.tenant_has_edited is False



def test_tenancy_information_can_only_be_edited_once_in_total():
    landlord = _make_user("landlord_single_edit")
    tenant = _make_user("tenant_single_edit")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    response = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert response.status_code == 201, response.data

    response_payload = response.data.get("data", response.data)
    tenancy_id = response_payload["id"]

    # Tenant uses the one-time edit.
    first_edit = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(date.today() + timedelta(days=14)),
            "duration_months": 12,
        },
        format="json",
    )

    assert first_edit.status_code == 200, first_edit.data

    # Landlord is now reviewing the counter-proposal, but no second edit
    # is permitted. The landlord must agree or cancel.
    second_edit = landlord_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(date.today() + timedelta(days=21)),
            "duration_months": 9,
        },
        format="json",
    )

    assert second_edit.status_code == 400, second_edit.data

    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert tenancy.proposed_by_id == tenant.id
    assert tenancy.move_in_date == date.today() + timedelta(days=14)
    assert tenancy.duration_months == 12
    assert tenancy.tenant_has_edited is True





def test_both_confirm_locks_schedule_and_sets_review_dates():
    landlord = _make_user("landlord_d")
    tenant = _make_user("tenant_d")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    # landlord proposes
    resp = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=5)),
            "duration_months": 6,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    payload = resp.data.get("data", resp.data)
    tenancy_id = payload["id"]

    # Tenant confirms. This is the second confirmation, so Timer 2
    # must become due approximately 10 minutes from now for QA.
    before_confirmation = timezone.now()

    resp2 = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={"action": "confirm"},
        format="json",
    )

    after_confirmation = timezone.now()

    assert resp2.status_code == 200, resp2.data

    tenancy = Tenancy.objects.get(id=tenancy_id)

    # after both confirmed, tenancy should have schedule fields
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.status in {Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE}

    assert tenancy.review_open_at is not None
    assert tenancy.still_living_check_at is not None
    
    expected_earliest = before_confirmation + timedelta(minutes=10)
    expected_latest = after_confirmation + timedelta(minutes=10)

    assert (
        expected_earliest
        <= tenancy.still_living_check_at
        <= expected_latest
    )


def test_second_party_cannot_overwrite_existing_proposal_through_propose_endpoint():
    landlord = _make_user("landlord_e")
    tenant = _make_user("tenant_e")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    tenant_move_in_date = date.today() + timedelta(days=10)

    # Tenant submits the original tenancy information.
    resp1 = tenant_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(tenant_move_in_date),
            "duration_months": 3,
        },
        format="json",
    )

    assert resp1.status_code == 201, resp1.data

    payload1 = resp1.data.get("data", resp1.data)
    tenancy_id = payload1["id"]

    # Landlord must review/respond to the existing proposal.
    # Calling the initial proposal endpoint again must not overwrite it.
    resp2 = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert resp2.status_code == 400, resp2.data
    assert Tenancy.objects.filter(room=room, tenant=tenant).count() == 1

    tenancy = Tenancy.objects.get(id=tenancy_id)

    # The original tenant proposal remains unchanged.
    assert tenancy.proposed_by_id == tenant.id
    assert tenancy.move_in_date == tenant_move_in_date
    assert tenancy.duration_months == 3
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.landlord_confirmed_at is None
    
    
    
def test_edit_immediately_completes_tenancy():
    landlord = _make_user("landlord_edit_confirm")
    tenant = _make_user("tenant_edit_confirm")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    # Landlord creates the original tenancy information.
    proposal_response = landlord_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": tenant.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert proposal_response.status_code == 201, proposal_response.data

    proposal_payload = proposal_response.data.get(
        "data",
        proposal_response.data,
    )
    tenancy_id = proposal_payload["id"]

    # Tenant uses the one-time Edit action.
    edit_response = tenant_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={
            "action": "propose_changes",
            "move_in_date": str(date.today() + timedelta(days=14)),
            "duration_months": 12,
        },
        format="json",
    )

    assert edit_response.status_code == 200, edit_response.data

    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert tenancy.proposed_by_id == tenant.id
    assert tenancy.landlord_confirmed_at is not None
    assert tenancy.tenant_confirmed_at is not None
    assert tenancy.status in {
        Tenancy.STATUS_CONFIRMED,
        Tenancy.STATUS_ACTIVE,
    }

    room.refresh_from_db()

    assert tenancy.review_open_at is not None
    assert tenancy.review_deadline_at is not None
    assert tenancy.still_living_check_at is not None
    assert room.is_available is False
    
    
    
def test_tenant_created_proposal_keeps_room_available():
    landlord = _make_user("landlord_tenant_first_available")
    tenant = _make_user("tenant_tenant_first_available")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenant_client = _api_client_for(tenant)

    response = tenant_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert response.status_code == 201, response.data

    room.refresh_from_db()

    assert room.is_available is True


def test_landlord_agreeing_to_tenant_created_proposal_makes_room_unavailable():
    landlord = _make_user("landlord_tenant_first_agree")
    tenant = _make_user("tenant_tenant_first_agree")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    proposal_response = tenant_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert proposal_response.status_code == 201, proposal_response.data

    proposal_payload = proposal_response.data.get(
        "data",
        proposal_response.data,
    )
    tenancy_id = proposal_payload["id"]

    room.refresh_from_db()
    assert room.is_available is True

    agree_response = landlord_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={"action": "confirm"},
        format="json",
    )

    assert agree_response.status_code == 200, agree_response.data

    room.refresh_from_db()
    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert room.is_available is False
    assert tenancy.status in {
        Tenancy.STATUS_CONFIRMED,
        Tenancy.STATUS_ACTIVE,
    }
    assert tenancy.still_living_check_at is not None


def test_landlord_rejecting_tenant_created_proposal_keeps_room_available():
    landlord = _make_user("landlord_tenant_first_reject")
    tenant = _make_user("tenant_tenant_first_reject")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    landlord_client = _api_client_for(landlord)
    tenant_client = _api_client_for(tenant)

    proposal_response = tenant_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert proposal_response.status_code == 201, proposal_response.data

    proposal_payload = proposal_response.data.get(
        "data",
        proposal_response.data,
    )
    tenancy_id = proposal_payload["id"]

    reject_response = landlord_client.post(
        f"{API_PREFIX}/tenancies/{tenancy_id}/respond/",
        data={"action": "cancel"},
        format="json",
    )

    assert reject_response.status_code == 200, reject_response.data

    room.refresh_from_db()
    tenancy = Tenancy.objects.get(id=tenancy_id)

    assert room.is_available is True
    assert tenancy.status == Tenancy.STATUS_CANCELLED
    assert tenancy.still_living_check_at is None
    assert tenancy.review_open_at is None


def test_unverified_tenant_created_proposal_expires_after_ten_minutes():
    landlord = _make_user("landlord_tenant_first_expiry")
    tenant = _make_user("tenant_tenant_first_expiry")
    room = _make_room(owner=landlord)
    _make_viewing_booking(user=tenant, room=room)

    tenant_client = _api_client_for(tenant)

    proposal_response = tenant_client.post(
        f"{API_PREFIX}/tenancies/propose/",
        data={
            "room_id": room.id,
            "counterparty_user_id": landlord.id,
            "move_in_date": str(date.today() + timedelta(days=7)),
            "duration_months": 6,
        },
        format="json",
    )

    assert proposal_response.status_code == 201, proposal_response.data

    proposal_payload = proposal_response.data.get(
        "data",
        proposal_response.data,
    )
    tenancy_id = proposal_payload["id"]

    tenancy = Tenancy.objects.get(id=tenancy_id)

    # TEMPORARY TESTING RULE:
    # Tenant-created proposals expire after 10 minutes.
    #
    # BEFORE PRODUCTION:
    # Change the application expiry back to 7 days.
    Tenancy.objects.filter(id=tenancy_id).update(
        created_at=timezone.now() - timedelta(minutes=11)
    )

    from propertylist_app.tasks import task_tenancy_prompts_sweep

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()
    room.refresh_from_db()

    assert tenancy.status == Tenancy.STATUS_CANCELLED
    assert room.is_available is True
    assert tenancy.still_living_check_at is None
    assert tenancy.review_open_at is None    