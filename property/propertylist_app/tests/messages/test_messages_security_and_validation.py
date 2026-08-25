import pytest
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import MessageThread, Message


pytestmark = pytest.mark.django_db


def _mk_users():
    u1 = User.objects.create_user(username="alice", email="a@x.com", password="pass12345")
    u2 = User.objects.create_user(username="bob", email="b@x.com", password="pass12345")
    u3 = User.objects.create_user(username="charlie", email="c@x.com", password="pass12345")
    return u1, u2, u3


def _mk_thread(u1, u2):
    t = MessageThread.objects.create()
    t.participants.set([u1, u2])
    return t


def test_thread_messages_requires_auth():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    anon = APIClient()
    r = anon.get(url)

    # depending on permission setup, you may return 401 or 403
    assert r.status_code in (401, 403)


def test_user_cannot_read_another_users_thread():
    u1, u2, u3 = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u3)

    r = client.get(url)

    # your API may choose 404 (hide existence) or 403 (explicit deny)
    assert r.status_code in (403, 404)


def test_user_cannot_post_to_thread_they_are_not_participant_of():
    u1, u2, u3 = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u3)

    r = client.post(url, {"body": "hello"}, format="json")

    assert r.status_code in (403, 404)


def test_blank_message_rejected():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u1)

    r = client.post(url, {"body": ""}, format="json")
    assert r.status_code == 400


def test_cursor_pagination_no_duplicates_no_skips_across_pages():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    base = timezone.now() - timedelta(minutes=20)

    # create 12 messages with deterministic ordering
    created_ids = []
    for i in range(12):
        m = Message.objects.create(
            thread=t,
            sender=u1 if i % 2 == 0 else u2,
            body=f"m{i+1}",
            created=base + timedelta(minutes=i),
        )
        created_ids.append(m.id)

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u1)

    seen_ids = []
    next_url = url

    # iterate pages until exhausted
    while next_url:
        resp = client.get(next_url)
        assert resp.status_code == 200
        assert "results" in resp.data

        page_ids = [item["id"] for item in resp.data["results"]]
        # no duplicates within page
        assert len(page_ids) == len(set(page_ids))

        seen_ids.extend(page_ids)
        next_url = resp.data.get("next")

    # no duplicates across pages
    assert len(seen_ids) == len(set(seen_ids))

    # and we saw all 12 messages
    assert set(seen_ids) == set(created_ids)


def test_cursor_consistency_when_new_message_arrives_between_page_fetches():
    u1, u2, _ = _mk_users()
    t = _mk_thread(u1, u2)

    base = timezone.now() - timedelta(minutes=20)

    # 7 messages total so we will have 2 pages if page size is 5 (as your existing test assumes)
    for i in range(7):
        Message.objects.create(
            thread=t,
            sender=u1 if i % 2 == 0 else u2,
            body=f"old-{i+1}",
            created=base + timedelta(minutes=i),
        )

    url = reverse("v1:thread-messages", kwargs={"thread_id": t.pk})

    client = APIClient()
    client.force_authenticate(user=u1)

    r1 = client.get(url, {"limit": 5})
    assert r1.status_code == 200
    page1_ids = [item["id"] for item in r1.data["data"]]
    next_url = r1.data.get("meta", {}).get("next")
    assert next_url

    # a new message arrives after page 1 was fetched
    new_msg = Message.objects.create(
        thread=t,
        sender=u2,
        body="new-between-pages",
        created=timezone.now(),
    )

    r2 = client.get(next_url)
    assert r2.status_code == 200
    page2_ids = [item["id"] for item in r2.data["data"]]

    # expectation under limit/offset pagination:
    # page 2 should NOT include the newly-created message,
    # but duplicates across pages can happen if a new record is inserted
    assert new_msg.id not in page2_ids
    
    
def test_still_living_message_update_tenancy_action_expires(
    user_factory,
    room_factory,
):
    from propertylist_app.models import Tenancy

    landlord = user_factory(
        username="ending_action_landlord",
    )
    tenant = user_factory(
        username="ending_action_tenant",
    )

    room = room_factory(
        property_owner=landlord,
    )

    now = timezone.now()

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() - timedelta(days=90),
        duration_months=3,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),

        # Timer 2 is already active.
        still_living_check_at=now - timedelta(minutes=1),

        # QA update window is still open.
        review_open_at=now + timedelta(minutes=10),

        still_living_confirmed_at=None,
        still_living_landlord_confirmed_at=None,
        still_living_tenant_confirmed_at=None,
    )

    thread = _mk_thread(
        landlord,
        tenant,
    )

    message = Message.objects.create(
        thread=thread,
        sender=landlord,
        body=(
            "Your tenancy is ending soon.\n\n"
            "You can update or renew the tenancy during this window."
        ),
        metadata={
            "system_event": True,
            "event_type": "still_living_check",
            "tenancy_id": tenancy.id,
            "room_id": room.id,
            "available_actions": ["update_tenancy"],
        },
    )

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse(
        "v1:thread-messages",
        kwargs={"thread_id": thread.id},
    )

    def get_message():
        response = client.get(url)
        assert response.status_code == 200

        payload = response.data.get(
            "data",
            response.data.get("results", []),
        )

        return next(
            item
            for item in payload
            if item["id"] == message.id
        )

    # -------------------------------------------------
    # 1. Window open:
    # button must be available.
    # -------------------------------------------------
    item = get_message()

    assert item["available_actions"] == [
        "update_tenancy",
    ]

    # -------------------------------------------------
    # 2. QA window expired:
    # button must disappear.
    # -------------------------------------------------
    tenancy.review_open_at = (
        timezone.now() - timedelta(seconds=1)
    )
    tenancy.save(
        update_fields=[
            "review_open_at",
        ]
    )

    item = get_message()

    assert item["available_actions"] == []

    # -------------------------------------------------
    # 3. Ended tenancy:
    # button must remain unavailable.
    # -------------------------------------------------
    tenancy.review_open_at = (
        timezone.now() + timedelta(minutes=10)
    )
    tenancy.status = Tenancy.STATUS_ENDED
    tenancy.save(
        update_fields=[
            "review_open_at",
            "status",
        ]
    )

    item = get_message()

    assert item["available_actions"] == []

    # -------------------------------------------------
    # 4. Still-living flow already completed:
    # button must remain unavailable.
    # -------------------------------------------------
    tenancy.status = Tenancy.STATUS_ACTIVE
    tenancy.still_living_confirmed_at = timezone.now()
    tenancy.save(
        update_fields=[
            "status",
            "still_living_confirmed_at",
        ]
    )

    item = get_message()

    assert item["available_actions"] == []    
    
    
def test_tenancy_proposal_message_body_is_viewer_specific(
    user_factory,
    room_factory,
):
    from propertylist_app.models import Tenancy
    from propertylist_app.services.tenancy_chat import post_tenancy_event

    landlord = user_factory(
        username="proposal_body_landlord",
    )
    tenant = user_factory(
        username="proposal_body_tenant",
    )

    room = room_factory(
        property_owner=landlord,
    )

    now = timezone.now()

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
        landlord_confirmed_at=None,
        tenant_confirmed_at=None,
    )

    thread, message = post_tenancy_event(
        tenancy=tenancy,
        event_type="proposed",
        sender=tenant,
    )

    url = reverse(
        "v1:thread-messages",
        kwargs={"thread_id": thread.id},
    )

    # -------------------------------------------------
    # Tenant is the proposer:
    # must see acknowledgement copy.
    # -------------------------------------------------
    tenant_client = APIClient()
    tenant_client.force_authenticate(user=tenant)

    tenant_response = tenant_client.get(
        url,
        {"limit": 100},
    )

    assert tenant_response.status_code == 200

    tenant_payload = tenant_response.data.get(
        "data",
        tenant_response.data.get("results", []),
    )

    tenant_message = next(
        item
        for item in tenant_payload
        if item["id"] == message.id
    )

    tenant_body = tenant_message["body"]

    assert "You submitted tenancy information for" in tenant_body
    assert room.title in tenant_body
    assert "Move-in date:" in tenant_body
    assert "Duration: 6 months" in tenant_body
    assert "Monthly rent:" in tenant_body
    assert "Your landlord has been asked to review these details." in tenant_body

    assert (
        "Please review the proposed tenancy details below before responding."
        not in tenant_body
    )
    assert (
        "Not rented to this person"
        not in tenant_body
    )

    # -------------------------------------------------
    # Landlord is the counterparty:
    # must see the original actionable copy.
    # -------------------------------------------------
    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)

    landlord_response = landlord_client.get(
        url,
        {"limit": 100},
    )

    assert landlord_response.status_code == 200

    landlord_payload = landlord_response.data.get(
        "data",
        landlord_response.data.get("results", []),
    )

    landlord_message = next(
        item
        for item in landlord_payload
        if item["id"] == message.id
    )

    landlord_body = landlord_message["body"]

    assert (
        "Please review the proposed tenancy details below before responding."
        in landlord_body
    )
    assert room.title in landlord_body
    assert "Move-in date:" in landlord_body
    assert "Duration: 6 months" in landlord_body
    assert "Monthly rent:" in landlord_body
    assert (
        "Please confirm that you actually rented this room to this tenant"
        in landlord_body
    )
    assert "Not rented to this person" in landlord_body

    assert (
        "You submitted tenancy information for"
        not in landlord_body
    ) 
    
    
@pytest.mark.django_db
def test_sender_only_sees_read_after_recipient_opens_thread():
    from propertylist_app.models import MessageRead

    sender, recipient, _ = _mk_users()
    thread = _mk_thread(sender, recipient)

    message = Message.objects.create(
        thread=thread,
        sender=sender,
        body="read receipt test",
    )

    messages_url = reverse(
        "v1:thread-messages",
        kwargs={"thread_id": thread.id},
    )

    read_url = reverse(
        "v1:thread-mark-read",
        kwargs={"thread_id": thread.id},
    )

    # -------------------------------------------------
    # Sender checks thread BEFORE recipient has opened it
    # -------------------------------------------------
    sender_client = APIClient()
    sender_client.force_authenticate(user=sender)

    sender_response = sender_client.get(messages_url)

    assert sender_response.status_code == 200

    sender_results = sender_response.data.get(
        "data",
        sender_response.data.get("results", []),
    )

    sender_message = next(
        item
        for item in sender_results
        if item["id"] == message.id
    )

    assert sender_message["is_read"] is False
    assert sender_message["read_at"] is None

    assert not MessageRead.objects.filter(
        message=message,
        user=recipient,
    ).exists()

    # -------------------------------------------------
    # Recipient actually opens/marks the thread read
    # -------------------------------------------------
    recipient_client = APIClient()
    recipient_client.force_authenticate(user=recipient)

    read_response = recipient_client.post(
        read_url,
        {},
        format="json",
    )

    assert read_response.status_code == 200

    receipt = MessageRead.objects.filter(
        message=message,
        user=recipient,
    ).first()

    assert receipt is not None

    # -------------------------------------------------
    # Sender fetches again AFTER recipient read it
    # -------------------------------------------------
    sender_response_after = sender_client.get(messages_url)

    assert sender_response_after.status_code == 200

    sender_results_after = sender_response_after.data.get(
        "data",
        sender_response_after.data.get("results", []),
    )

    sender_message_after = next(
        item
        for item in sender_results_after
        if item["id"] == message.id
    )

    assert sender_message_after["is_read"] is True
    assert sender_message_after["read_at"] is not None       
