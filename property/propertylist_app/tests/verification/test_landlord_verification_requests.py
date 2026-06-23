import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from propertylist_app.models import LandlordVerificationRequest, UserProfile


pytestmark = pytest.mark.django_db


LANDLORD_URL = "/api/v1/users/me/landlord-verification/"
ADMIN_LIST_URL = "/api/v1/admin/support/landlord-verification-requests/"


def make_user(username, role="seeker", admin_role="", is_staff=False, is_superuser=False):
    User = get_user_model()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="StrongPass123!",
        is_staff=is_staff,
        is_superuser=is_superuser,
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = role
    profile.admin_role = admin_role
    profile.save(update_fields=["role", "admin_role"])

    return user


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def fake_document(name="id-document.pdf"):
    return SimpleUploadedFile(
        name,
        b"fake verification document content",
        content_type="application/pdf",
    )


def test_landlord_can_submit_verification_request():
    landlord = make_user("verify_landlord", role="landlord")
    client = auth_client(landlord)

    response = client.post(
        LANDLORD_URL,
        data={
            "document": fake_document(),
            "notes": "Please verify my advertiser profile.",
        },
        format="multipart",
    )

    assert response.status_code == 201, response.data
    assert response.data["ok"] is True
    assert LandlordVerificationRequest.objects.filter(user=landlord).count() == 1

    request_obj = LandlordVerificationRequest.objects.get(user=landlord)
    assert request_obj.status == LandlordVerificationRequest.STATUS_PENDING


def test_seeker_cannot_submit_landlord_verification_request():
    seeker = make_user("verify_seeker", role="seeker")
    client = auth_client(seeker)

    response = client.post(
        LANDLORD_URL,
        data={
            "document": fake_document(),
            "notes": "I should not be allowed.",
        },
        format="multipart",
    )

    assert response.status_code == 403, response.data
    assert LandlordVerificationRequest.objects.filter(user=seeker).count() == 0


def test_duplicate_pending_request_is_not_created():
    landlord = make_user("verify_duplicate", role="landlord")
    client = auth_client(landlord)

    first_response = client.post(
        LANDLORD_URL,
        data={"document": fake_document("first.pdf")},
        format="multipart",
    )
    assert first_response.status_code == 201, first_response.data

    second_response = client.post(
        LANDLORD_URL,
        data={"document": fake_document("second.pdf")},
        format="multipart",
    )

    assert second_response.status_code == 200, second_response.data
    assert LandlordVerificationRequest.objects.filter(user=landlord).count() == 1


def test_support_admin_can_approve_request_and_sets_badge_true():
    landlord = make_user("verify_approve_landlord", role="landlord")
    support_admin = make_user(
        "verify_support_admin",
        role="seeker",
        admin_role="support_admin",
        is_staff=True,
    )

    verification_request = LandlordVerificationRequest.objects.create(
        user=landlord,
        document=fake_document(),
        status=LandlordVerificationRequest.STATUS_PENDING,
    )

    client = auth_client(support_admin)

    response = client.post(
        f"{ADMIN_LIST_URL}{verification_request.id}/review/",
        data={"action": "approve"},
        format="json",
    )

    assert response.status_code == 200, response.data

    verification_request.refresh_from_db()
    landlord.profile.refresh_from_db()

    assert verification_request.status == LandlordVerificationRequest.STATUS_APPROVED
    assert verification_request.reviewed_by == support_admin
    assert verification_request.reviewed_at is not None
    assert landlord.profile.advertiser_verified is True


def test_support_admin_can_reject_request_and_badge_stays_false():
    landlord = make_user("verify_reject_landlord", role="landlord")
    support_admin = make_user(
        "verify_reject_support",
        role="seeker",
        admin_role="support_admin",
        is_staff=True,
    )

    verification_request = LandlordVerificationRequest.objects.create(
        user=landlord,
        document=fake_document(),
        status=LandlordVerificationRequest.STATUS_PENDING,
    )

    client = auth_client(support_admin)

    response = client.post(
        f"{ADMIN_LIST_URL}{verification_request.id}/review/",
        data={
            "action": "reject",
            "rejection_reason": "Uploaded document is unclear.",
        },
        format="json",
    )

    assert response.status_code == 200, response.data

    verification_request.refresh_from_db()
    landlord.profile.refresh_from_db()

    assert verification_request.status == LandlordVerificationRequest.STATUS_REJECTED
    assert verification_request.rejection_reason == "Uploaded document is unclear."
    assert landlord.profile.advertiser_verified is False


def test_rejection_requires_reason():
    landlord = make_user("verify_reject_reason_landlord", role="landlord")
    support_admin = make_user(
        "verify_reject_reason_support",
        role="seeker",
        admin_role="support_admin",
        is_staff=True,
    )

    verification_request = LandlordVerificationRequest.objects.create(
        user=landlord,
        document=fake_document(),
        status=LandlordVerificationRequest.STATUS_PENDING,
    )

    client = auth_client(support_admin)

    response = client.post(
        f"{ADMIN_LIST_URL}{verification_request.id}/review/",
        data={"action": "reject"},
        format="json",
    )

    assert response.status_code == 400, response.data

    verification_request.refresh_from_db()
    landlord.profile.refresh_from_db()

    assert verification_request.status == LandlordVerificationRequest.STATUS_PENDING
    assert landlord.profile.advertiser_verified is False