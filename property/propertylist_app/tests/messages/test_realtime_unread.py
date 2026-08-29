"""
BE-03 — conversation-scoped + role-scoped unread totals.

The backend now computes unread at three granularities (account, role,
conversation) in one shared module (services.messaging_unread) and pushes the
role + conversation numbers on the realtime events, so the frontend can write
them instead of refetching. These tests pin the semantics that matter:

  * a message is unread when it's a system event, or sent by another
    participant, and the user has no MessageRead row for it;
  * binned threads never count;
  * unscoped threads count in *both* role totals (matching how the role-scoped
    thread lists show them), so account != landlord + seeker;
  * conversation totals sum across every thread sharing one room.
"""

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from unittest.mock import patch

from propertylist_app.models import (
    Message,
    MessageRead,
    MessageThread,
    MessageThreadState,
    Room,
    RoomCategorie,
)
from propertylist_app.services import messaging_unread as unread_svcs


pytestmark = pytest.mark.django_db


def _mk_user(username: str) -> User:
    return User.objects.create_user(username=username, password="pass12345")


def _mk_room(owner: User, key_suffix: str = "") -> Room:
    cat = RoomCategorie.objects.create(
        name="General",
        key=f"general-{owner.username}{key_suffix}",
    )
    return Room.objects.create(
        title=f"Room {owner.username}{key_suffix}",
        description="desc",
        price_per_month="500.00",
        location="London",
        category=cat,
        property_owner=owner,
        property_type="flat",
        status="active",
    )


def _thread(landlord=None, seeker=None, room=None):
    thread = MessageThread.objects.create(room=room)
    participants = [u for u in (landlord, seeker) if u is not None]
    if participants:
        thread.participants.set(participants)
    if landlord is not None:
        thread.landlord = landlord
    if seeker is not None:
        thread.seeker = seeker
    if landlord is not None or seeker is not None:
        thread.save(update_fields=["landlord", "seeker"])
    return thread


def _msg(thread, sender, body="hi", system_event=False):
    return Message.objects.create(
        thread=thread,
        sender=sender,
        body=body,
        message_type=Message.TYPE_TEXT,
        metadata={"system_event": True} if system_event else {},
    )


def test_unread_totals_account_and_roles():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")

    # Seeker-role thread (seeker is the seeker): landlord sent one unread msg.
    t1 = _thread(landlord=landlord, seeker=seeker)
    _msg(t1, landlord)

    # Landlord-role thread (seeker is the landlord): landlord sent one unread.
    t2 = _thread(landlord=seeker, seeker=landlord)
    _msg(t2, landlord)

    totals = unread_svcs.unread_totals(seeker)
    assert totals["account"] == 2
    assert totals["landlord"] == 1  # t2 — seeker wears the landlord hat
    assert totals["seeker"] == 1  # t1 — seeker wears the seeker hat


def test_unread_totals_unscoped_thread_counts_in_both_roles():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")

    # Unscoped: neither landlord nor seeker snapshot set.
    t = _thread()
    t.participants.set([landlord, seeker])
    _msg(t, landlord)

    totals = unread_svcs.unread_totals(seeker)
    # The thread matches neither role filter, so it counts in neither role
    # total — but it is still the seeker's unread account-wide.
    assert totals["account"] == 1
    assert totals["landlord"] == 0
    assert totals["seeker"] == 0


def test_unread_totals_binned_thread_excluded():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")

    t = _thread(landlord=landlord, seeker=seeker)
    _msg(t, landlord)
    MessageThreadState.objects.create(user=seeker, thread=t, in_bin=True)

    totals = unread_svcs.unread_totals(seeker)
    assert totals["account"] == 0
    assert totals["seeker"] == 0


def test_unread_totals_system_event_counts_for_both_participants():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")

    t = _thread(landlord=landlord, seeker=seeker)
    # A system event is stamped with a real sender but is unread for everyone.
    _msg(t, landlord, system_event=True)

    assert unread_svcs.unread_totals(landlord)["account"] == 1
    assert unread_svcs.unread_totals(seeker)["account"] == 1


def test_conversation_unread_count_sums_across_room_threads():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")
    room = _mk_room(landlord)

    # Two threads about the same room — one conversation.
    t1 = _thread(landlord=landlord, seeker=seeker, room=room)
    t2 = _thread(landlord=landlord, seeker=seeker, room=room)
    _msg(t1, landlord)
    _msg(t2, landlord)

    assert unread_svcs.conversation_unread_count(seeker, room.id) == 2


def test_conversation_unread_count_ignores_other_rooms():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")
    room_a = _mk_room(landlord, key_suffix="a")
    room_b = _mk_room(landlord, key_suffix="b")

    t1 = _thread(landlord=landlord, seeker=seeker, room=room_a)
    t2 = _thread(landlord=landlord, seeker=seeker, room=room_b)
    _msg(t1, landlord)
    _msg(t2, landlord)

    assert unread_svcs.conversation_unread_count(seeker, room_a.id) == 1
    assert unread_svcs.conversation_unread_count(seeker, room_b.id) == 1


def test_participant_role():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")

    t = _thread(landlord=landlord, seeker=seeker)
    assert unread_svcs.participant_role(landlord, t) == "landlord"
    assert unread_svcs.participant_role(seeker, t) == "seeker"

    # Unscoped: no role snapshot.
    t2 = _thread()
    assert unread_svcs.participant_role(landlord, t2) == "unscoped"


def test_mark_read_emits_role_and_conversation_totals():
    landlord = _mk_user("landlord")
    seeker = _mk_user("seeker")
    room = _mk_room(landlord)

    t = _thread(landlord=landlord, seeker=seeker, room=room)
    _msg(t, landlord)

    client = APIClient()
    client.force_authenticate(user=seeker)

    with patch(
        "propertylist_app.api.views.messaging.push_user_realtime_event"
    ) as realtime:
        response = client.post(f"/api/v1/messages/threads/{t.id}/read/")

    assert response.status_code == 200

    realtime.assert_any_call(
        seeker.id,
        "unread_count_changed",
        {
            "thread_id": t.id,
            "thread_unread_count": 0,
            "account_unread_total": 0,
            "role": "seeker",
            "relationship_id": room.id,
            "conversation_unread_count": 0,
            "role_unread_totals": {
                "landlord": 0,
                "seeker": 0,
            },
        },
    )
