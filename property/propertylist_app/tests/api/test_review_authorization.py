# propertylist_app/tests/api/test_review_authorization.py
"""
Object-level authorisation on GET /api/v1/reviews/ and GET /api/v1/reviews/{id}/.

Regression coverage for the BOLA/IDOR finding (see security/FINDING-review-idor.md
in the frontend repo): a review is private to its two parties and written blind.
A caller who is neither reviewer nor reviewee must get 404 regardless of reveal
state, and the reviewee must not read the review about them before reveal_at.

Verifies the contract the frontend already assumes: the flat /reviews/ list
"only returns the caller's own reviews" (see reviews-modal.tsx).
"""

from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _get_model(app_label, model_name):
    return apps.get_model(app_label, model_name)


def _list_url():
    return "/api/v1/reviews/"


def _detail_url(review_id):
    return f"/api/v1/reviews/{review_id}/"


def _make_tenancy(room, landlord, tenant, *, deadline_offset_days):
    """Tenancy whose review deadline is `deadline_offset_days` from now."""
    Tenancy = _get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    t = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
    )
    if hasattr(t, "review_open_at"):
        t.review_open_at = now - timedelta(days=10)
    if hasattr(t, "review_deadline_at"):
        t.review_deadline_at = now + timedelta(days=deadline_offset_days)
    t.save()
    return t


def _create_review(*, tenancy, landlord, tenant, role, active, notes):
    Review = _get_model("propertylist_app", "Review")
    return Review.objects.create(
        tenancy=tenancy,
        reviewer=landlord,
        reviewee=tenant,
        role=role,
        overall_rating=4,
        notes=notes,
        active=active,
    )


def _revealed_pair(user_factory, room_factory):
    """
    landlord <-> tenant with BOTH reviews REVEALED (active=True,
    reveal_at in the past, e.g. after the reveal sweep fired).
    Returns (landlord, tenant, room, landlord_review, tenant_review).
    """
    Review = _get_model("propertylist_app", "Review")
    landlord = user_factory(username="az_landlord_revealed", email="azlandlord@example.com")
    tenant = user_factory(username="az_tenant_revealed", email="ztenant@example.com")
    room = room_factory(property_owner=landlord, title="Revealed tenancy room")

    tenancy = _make_tenancy(room, landlord, tenant, deadline_offset_days=-1)

    landlord_review = _create_review(
        tenancy=tenancy,
        landlord=landlord,
        tenant=tenant,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        active=True,
        notes="The landlord's private words about the tenant.",
    )
    tenant_review = _create_review(
        tenancy=tenancy,
        landlord=landlord,
        tenant=tenant,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        active=True,
        notes="The tenant's private words about the landlord.",
    )
    return landlord, tenant, room, landlord_review, tenant_review


def _hidden_review(user_factory, room_factory):
    """
    landlord <-> tenant with one HIDDEN review (active=False, reveal_at in the
    future — the state every serializer-created review is born in).
    Returns (landlord, tenant, room, hidden_about_tenant.
    """
    Review = _get_model("propertylist_app", "Review")
    landlord = user_factory(username="az_landlord_hidden", email="azlandlordhidden@example.com")
    tenant = user_factory(username="az_tenant_hidden", email="aztenanthidden@example.com")
    room = room_factory(property_owner=landlord, title="Hidden tenancy room")

    tenancy = _make_tenancy(room, landlord, tenant, deadline_offset_days=7)

    hidden = _create_review(
        tenancy=tenancy,
        landlord=landlord,
        tenant=tenant,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        active=False,
        notes="Still blind, must not be readable.",
    )
    return landlord, tenant, room, tenancy, hidden


# --------------------------------------------------------------------------- #
# Detail endpoint — GET /reviews/{id}/
# --------------------------------------------------------------------------- #


def test_detail_hidden_review_returns_404_to_non_party(user_factory, room_factory):
    """Non-participant probing a pre-reveal review gets 404, not the body."""
    landlord, tenant, room, tenancy, hidden = _hidden_review(user_factory, room_factory)
    attacker = user_factory(username="az_attacker_hidden", email="azattackerhidden@example.com")

    client = APIClient()
    client.force_authenticate(user=attacker)

    res = client.get(_detail_url(hidden.id))

    assert res.status_code == 404


def test_detail_revealed_review_returns_404_to_non_party(user_factory, room_factory):
    """
    Non-participant walking review ids of REVEALED reviews still gets 404.
    This is the cross-account read the reproduce script classified as LEAK:
    before the fix, `reveal_at <= now` made any revealed review readable by
    any signed-in user.
    """
    landlord, tenant, room, landlord_review, tenant_review = _revealed_pair(
        user_factory, room_factory
    )
    attacker = user_factory(username="az_attacker_revealed", email="azattackerrevealed@example.com")

    client = APIClient()
    client.force_authenticate(user=attacker)

    for review in (landlord_review, tenant_review):
        res = client.get(_detail_url(review.id))
        assert res.status_code == 404, review.id
        assert "notes" not in res.content.decode(), "body leaked to a third party"


def test_detail_reviewee_cannot_read_before_reveal(user_factory, room_factory):
    """The subject cannot read the review about them inside the blind window."""
    landlord, tenant, room, tenancy, hidden = _hidden_review(user_factory, room_factory)

    client = APIClient()
    client.force_authenticate(user=tenant)
    res = client.get(_detail_url(hidden.id))

    assert res.status_code == 404


def test_detail_reviewee_can_read_after_reveal(user_factory, room_factory):
    landlord, tenant, room, landlord_review, tenant_review = _revealed_pair(
        user_factory, room_factory
    )

    client = APIClient()
    client.force_authenticate(user=tenant)
    res = client.get(_detail_url(landlord_review.id))

    assert res.status_code == 200
    assert res.data["notes"] == landlord_review.notes


def test_detail_reviewer_can_read_own_review(user_factory, room_factory):
    """The writer may always read their own review, revealed or not."""
    landlord, tenant, room, landlord_review, tenant_review = _revealed_pair(
        user_factory, room_factory
    )

    client = APIClient()
    client.force_authenticate(user=landlord)
    res = client.get(_detail_url(landlord_review.id))

    assert res.status_code == 200
    assert res.data["id"] == landlord_review.id


# --------------------------------------------------------------------------- #
# List endpoint — GET /reviews/
# --------------------------------------------------------------------------- #


def test_list_excludes_other_users_reviews(user_factory, room_factory):
    """
    The flat list returns only the caller's own reviews — never revealed
    reviews belonging to two other people. Before the fix the list leaked
    every revealed review platform-wide via the `reveal_at <= now` disjunct.
    """
    landlord, tenant, room, landlord_review, tenant_review = _revealed_pair(
        user_factory, room_factory
    )
    attacker = user_factory(username="az_attacker_list", email="azattackerlist@example.com")

    client = APIClient()
    client.force_authenticate(user=attacker)
    res = client.get(_list_url())

    assert res.status_code == 200
    ids = [item["id"] for item in res.data["data"]]
    assert landlord_review.id not in ids
    assert tenant_review.id not in ids


def test_list_shows_only_own_revealed_incoming(user_factory, room_factory):
    """
    The tenant sees in their own list: the revealed review about them and their
    own written review. Their incoming review still within the blind window
    (active=True row with a future reveal) is excluded until reveal.
    """
    Review = _get_model("propertylist_app", "Review")
    landlord = user_factory(username="az_landlord_own", email="azlandlordown@example.com")
    tenant = user_factory(username="az_tenant_own", email="aztenantown@example.com")
    room = room_factory(property_owner=landlord, title="Own list room")

    tenancy = _make_tenancy(room, landlord, tenant, deadline_offset_days=7)

    # Revealed incoming review — deadline already past.
    incoming_past = Review.objects.create(
        tenancy=tenancy,
        reviewer=landlord,
        reviewee=tenant,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        overall_rating=4,
        notes="Visible to the tenant again",
        active=True,
    )
    incoming_past.reveal_at = timezone.now() - timedelta(days=1)
    incoming_past.save(update_fields=["reveal_at"])

    # Still-blind incoming review — active row whose reveal is in the future
    # (the state the detail gate's defensive branch also protects).
    incoming_future = Review.objects.create(
        tenancy=tenancy,
        reviewer=landlord,
        reviewee=tenant,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        overall_rating=4,
        notes="Must stay hidden",
        active=True,
    )
    incoming_future.reveal_at = timezone.now() + timedelta(days=1)
    incoming_future.save(update_fields=["reveal_at"])

    client = APIClient()
    client.force_authenticate(user=tenant)
    res = client.get(_list_url())

    assert res.status_code == 200
    ids = [item["id"] for item in res.data["data"]]
    assert incoming_past.id in ids  # after reveal it belongs to the tenant
    assert incoming_future.id not in ids  # blind until reveal