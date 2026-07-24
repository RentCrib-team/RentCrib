import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


def make_user():
    user = User.objects.create_user(
        username="batch2profile",
        email="batch2profile@example.com",
        password="StrongPass1!",
        first_name="Batch",
        last_name="Two",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.role = "seeker"
    profile.save(update_fields=["email_verified", "role"])
    return user


def _payload_data(body):
    if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
        return body["data"]
    return body


def _field_errors(body):
    if not isinstance(body, dict):
        return {}

    if isinstance(body.get("field_errors"), dict):
        return body["field_errors"]

    if isinstance(body.get("details"), dict):
        return body["details"]

    if isinstance(body.get("errors"), dict):
        return body["errors"]

    return body


def test_user_profile_get_returns_profile(api_client):
    user = make_user()
    url = reverse("api:user-profile")

    api_client.force_authenticate(user=user)
    response = api_client.get(url, format="json")

    assert response.status_code == 200, response.json()

    body = response.json()
    data = _payload_data(body)

    assert data["user"] == user.id
    assert data["role"] == "seeker"
    assert data["email_verified"] is True


def test_user_profile_patch_updates_fields(api_client):
    user = make_user()
    url = reverse("api:user-profile")

    api_client.force_authenticate(user=user)
    response = api_client.patch(
        url,
        {
            "occupation": "Software engineer",
            "postcode": "sw1a1aa",
            "date_of_birth": "1990-01-01",
            "gender": "male",
            "about_you": "Friendly and tidy.",
            "role": "seeker",
            "role_detail": "current_flatmate",
            "address_manual": "10 Downing Street, London",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()

    profile = UserProfile.objects.get(user=user)

    assert profile.occupation == "Software engineer"
    assert profile.postcode == "SW1A 1AA"
    assert str(profile.date_of_birth) == "1990-01-01"
    assert profile.gender == "male"
    assert profile.role == "seeker"
    assert profile.role_detail == "current_flatmate"
    assert profile.address_manual == "10 Downing Street, London"
    assert profile.about_you == "Friendly and tidy."


def test_user_profile_rejects_html_in_occupation(api_client):
    user = make_user()
    url = reverse("api:user-profile")

    api_client.force_authenticate(user=user)
    response = api_client.patch(
        url,
        {
            "occupation": "<script>alert(1)</script>",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()

    body = response.json()
    field_errors = _field_errors(body)

    assert "occupation" in field_errors

    profile = UserProfile.objects.get(user=user)
    assert profile.occupation != "<script>alert(1)</script>"


def test_user_profile_rejects_html_in_about_you(api_client):
    user = make_user()
    url = reverse("api:user-profile")

    api_client.force_authenticate(user=user)
    response = api_client.patch(
        url,
        {
            "about_you": "<img src=x onerror=alert(1)>",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()

    body = response.json()
    field_errors = _field_errors(body)

    assert "about_you" in field_errors

    profile = UserProfile.objects.get(user=user)
    assert profile.about_you != "<img src=x onerror=alert(1)>"


def test_user_profile_rejects_dangerous_javascript_scheme(api_client):
    user = make_user()
    url = reverse("api:user-profile")

    api_client.force_authenticate(user=user)
    response = api_client.patch(
        url,
        {
            "about_you": "javascript:alert(1)",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()

    body = response.json()
    field_errors = _field_errors(body)

    assert "about_you" in field_errors

    profile = UserProfile.objects.get(user=user)
    assert profile.about_you != "javascript:alert(1)"


def test_onboarding_complete_sets_flag(api_client):
    user = make_user()
    url = reverse("api:user-onboarding-complete")

    api_client.force_authenticate(user=user)
    response = api_client.post(
        url,
        {"confirm": True},
        format="json",
    )

    assert response.status_code == 200, response.json()

    body = response.json()

    assert body["ok"] is True
    assert body["data"]["onboarding_completed"] is True

    profile = UserProfile.objects.get(user=user)
    assert profile.onboarding_completed is True


def test_profile_page_returns_expected_shape(api_client):
    user = make_user()
    profile = UserProfile.objects.get(user=user)

    profile.occupation = "Designer"
    profile.postcode = "SW1A 1AA"
    profile.address_manual = "London"
    profile.about_you = "Hello"
    profile.save(
        update_fields=[
            "occupation",
            "postcode",
            "address_manual",
            "about_you",
        ]
    )

    url = reverse("api:user-profile-page")

    api_client.force_authenticate(user=user)
    response = api_client.get(url, format="json")

    assert response.status_code == 200, response.json()

    body = response.json()

    assert body["ok"] is True

    data = body["data"]

    assert data["id"] == user.id
    assert data["email"] == user.email
    assert data["username"] == user.username
    assert data["role"] == profile.role
    assert data["occupation"] == "Designer"
    assert data["postcode"] == "SW1A 1AA"
    assert data["address_manual"] == "London"
    assert data["about_you"] == "Hello"
    assert "reviews_preview" in data