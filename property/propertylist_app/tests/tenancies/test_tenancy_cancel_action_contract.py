from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.api.serializers import TenancyDetailSerializer
from propertylist_app.models import Tenancy

pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _proposed_tenancy(*, room, landlord, tenant, proposed_by):
    now = timezone.now()
    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=proposed_by,
        move_in_date=date.today() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
        landlord_confirmed_at=now if proposed_by.id == landlord.id else None,
        tenant_confirmed_at=now if proposed_by.id == tenant.id else None,
    )


def _available_actions(tenancy, user):
    request = SimpleNamespace(user=user)
    return TenancyDetailSerializer(
        tenancy,
        context={"request": request},
    ).data["available_actions"]


def _cancel(client, tenancy):
    return client.post(
        f"{API_PREFIX}/tenancies/{tenancy.id}/respond/",
        data={
            "action": "cancel",
            "move_in_date": str(tenancy.move_in_date),
            "duration_months": tenancy.duration_months,
        },
        format="json",
    )


def test_proposer_can_withdraw_own_proposed_tenancy(user_factory, room_factory):
    landlord = user_factory(username="cancel_contract_landlord_withdraw")
    tenant = user_factory(username="cancel_contract_tenant_withdraw")
    room = room_factory(property_owner=landlord)
    room.is_available = False
    room.save(update_fields=["is_available"])

    tenancy = _proposed_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
    )

    assert "cancel" in _available_actions(tenancy, landlord)

    response = _cancel(_client(landlord), tenancy)

    assert response.status_code == 200, response.data
    tenancy.refresh_from_db()
    room.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CANCELLED
    assert room.is_available is True


def test_tenant_can_reject_landlord_proposal(user_factory, room_factory):
    landlord = user_factory(username="cancel_contract_landlord_tenant_reject")
    tenant = user_factory(username="cancel_contract_tenant_reject")
    room = room_factory(property_owner=landlord)
    room.is_available = False
    room.save(update_fields=["is_available"])

    tenancy = _proposed_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
    )

    assert "cancel" in _available_actions(tenancy, tenant)

    response = _cancel(_client(tenant), tenancy)

    assert response.status_code == 200, response.data
    tenancy.refresh_from_db()
    room.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CANCELLED
    assert room.is_available is True


def test_landlord_can_reject_tenant_first_claim_as_not_my_tenant(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="cancel_contract_landlord_disown")
    tenant = user_factory(username="cancel_contract_tenant_claim")
    room = room_factory(property_owner=landlord)
    tenancy = _proposed_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
    )

    assert "cancel" in _available_actions(tenancy, landlord)

    response = _cancel(_client(landlord), tenancy)

    assert response.status_code == 200, response.data
    tenancy.refresh_from_db()
    room.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CANCELLED
    assert room.is_available is True


def test_cancel_is_not_advertised_or_allowed_after_proposed_state(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="cancel_contract_landlord_closed")
    tenant = user_factory(username="cancel_contract_tenant_closed")
    room = room_factory(property_owner=landlord)
    tenancy = _proposed_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
    )
    tenancy.status = Tenancy.STATUS_CONFIRMED
    tenancy.save(update_fields=["status"])

    assert "cancel" not in _available_actions(tenancy, landlord)
    assert "cancel" not in _available_actions(tenancy, tenant)

    response = _cancel(_client(landlord), tenancy)

    assert response.status_code == 400, response.data
    tenancy.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CONFIRMED
