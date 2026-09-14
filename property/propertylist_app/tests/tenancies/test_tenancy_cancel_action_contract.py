from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

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
    tenancy = _proposed_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
    )

    response = _cancel(_client(landlord), tenancy)

    assert response.status_code == 200, response.data
    tenancy.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CANCELLED


def test_tenant_can_reject_landlord_proposal(user_factory, room_factory):
    landlord = user_factory(username="cancel_contract_landlord_tenant_reject")
    tenant = user_factory(username="cancel_contract_tenant_reject")
    room = room_factory(property_owner=landlord)
    tenancy = _proposed_tenancy(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
    )

    response = _cancel(_client(tenant), tenancy)

    assert response.status_code == 200, response.data
    tenancy.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CANCELLED


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

    response = _cancel(_client(landlord), tenancy)

    assert response.status_code == 200, response.data
    tenancy.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CANCELLED
