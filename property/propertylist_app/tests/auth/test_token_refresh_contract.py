import pytest
from django.contrib.auth import get_user_model

from propertylist_app.models import UserProfile


API_LOGIN_URL = "/api/v1/auth/login/"
API_REFRESH_URL = "/api/v1/auth/token/refresh/"


@pytest.mark.django_db
def test_token_refresh_rotates_refresh_token_and_returns_consistent_envelope(
    api_client,
):
    User = get_user_model()

    user = User.objects.create_user(
        username="refreshuser",
        email="refreshuser@example.com",
        password="Str0ng!Pass123",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])

    login = api_client.post(
        API_LOGIN_URL,
        {
            "identifier": "refreshuser",
            "password": "Str0ng!Pass123",
        },
        format="json",
    )

    assert login.status_code == 200

    original_refresh = login.data["data"]["tokens"]["refresh"]

    first_refresh = api_client.post(
        API_REFRESH_URL,
        {"refresh": original_refresh},
        format="json",
    )

    assert first_refresh.status_code == 200
    assert first_refresh.data["ok"] is True

    data = first_refresh.data["data"]

    assert isinstance(data["access"], str)
    assert isinstance(data["refresh"], str)
    assert data["refresh"] != original_refresh
    assert "access_expires_at" in data
    assert "refresh_expires_at" in data

    old_token_reuse = api_client.post(
        API_REFRESH_URL,
        {"refresh": original_refresh},
        format="json",
    )

    assert old_token_reuse.status_code == 400

    replacement_refresh = api_client.post(
        API_REFRESH_URL,
        {"refresh": data["refresh"]},
        format="json",
    )

    assert replacement_refresh.status_code == 200
    assert replacement_refresh.data["ok"] is True
    assert replacement_refresh.data["data"]["refresh"] != data["refresh"]


@pytest.mark.django_db
def test_token_refresh_invalid_refresh_returns_400(api_client):
    response = api_client.post(
        API_REFRESH_URL,
        {"refresh": "not-a-real-token"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_token_refresh_rejects_inactive_user(api_client):
    User = get_user_model()

    user = User.objects.create_user(
        username="inactive-refresh-user",
        email="inactive-refresh@example.com",
        password="Str0ng!Pass123",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])

    login = api_client.post(
        API_LOGIN_URL,
        {
            "identifier": "inactive-refresh-user",
            "password": "Str0ng!Pass123",
        },
        format="json",
    )

    assert login.status_code == 200

    refresh_token = login.data["data"]["tokens"]["refresh"]

    user.is_active = False
    user.save(update_fields=["is_active"])

    response = api_client.post(
        API_REFRESH_URL,
        {"refresh": refresh_token},
        format="json",
    )

    assert response.status_code == 400