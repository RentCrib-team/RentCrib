import hashlib

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from propertylist_app.models import UserProfile


API_LOGIN_URL = "/api/v1/auth/login/"
API_REFRESH_URL = "/api/v1/auth/token/refresh/"


def _create_verified_user(*, username: str, email: str):
    User = get_user_model()

    user = User.objects.create_user(
        username=username,
        email=email,
        password="Str0ng!Pass123",
    )

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])

    return user


def _login_and_get_refresh(api_client, *, identifier: str):
    response = api_client.post(
        API_LOGIN_URL,
        {
            "identifier": identifier,
            "password": "Str0ng!Pass123",
        },
        format="json",
    )

    assert response.status_code == 200

    return response.data["data"]["tokens"]["refresh"]


@pytest.mark.django_db
def test_token_refresh_rotates_refresh_token_and_returns_consistent_envelope(
    api_client,
):
    _create_verified_user(
        username="refreshuser",
        email="refreshuser@example.com",
    )

    original_refresh = _login_and_get_refresh(
        api_client,
        identifier="refreshuser",
    )

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

    # Immediate duplicate use represents a legitimate concurrent refresh race.
    # It must receive the exact same rotation result instead of a 400.
    duplicate_refresh = api_client.post(
        API_REFRESH_URL,
        {"refresh": original_refresh},
        format="json",
    )

    assert duplicate_refresh.status_code == 200
    assert duplicate_refresh.data["ok"] is True

    duplicate_data = duplicate_refresh.data["data"]

    assert duplicate_data["access"] == data["access"]
    assert duplicate_data["refresh"] == data["refresh"]
    assert duplicate_data["access_expires_at"] == data["access_expires_at"]
    assert duplicate_data["refresh_expires_at"] == data["refresh_expires_at"]

    # The replacement refresh remains usable normally.
    replacement_refresh = api_client.post(
        API_REFRESH_URL,
        {"refresh": data["refresh"]},
        format="json",
    )

    assert replacement_refresh.status_code == 200
    assert replacement_refresh.data["ok"] is True
    assert replacement_refresh.data["data"]["refresh"] != data["refresh"]


@pytest.mark.django_db
def test_token_refresh_old_token_is_rejected_after_dedupe_grace_is_removed(
    api_client,
):
    _create_verified_user(
        username="refresh-grace-user",
        email="refresh-grace@example.com",
    )

    original_refresh = _login_and_get_refresh(
        api_client,
        identifier="refresh-grace-user",
    )

    first_refresh = api_client.post(
        API_REFRESH_URL,
        {"refresh": original_refresh},
        format="json",
    )

    assert first_refresh.status_code == 200

    token_hash = hashlib.sha256(
        original_refresh.encode("utf-8")
    ).hexdigest()

    # Simulate expiry of only the dedupe grace result.
    # Do NOT clear the whole cache because that can interfere with unrelated
    # throttling/auth state used by other tests.
    cache.delete(
        f"auth:refresh:result:{token_hash}"
    )

    # Remove the short-lived processing lock too so this request reaches
    # SimpleJWT and proves the original token is still genuinely blacklisted.
    cache.delete(
        f"auth:refresh:lock:{token_hash}"
    )

    expired_grace_reuse = api_client.post(
        API_REFRESH_URL,
        {"refresh": original_refresh},
        format="json",
    )

    assert expired_grace_reuse.status_code == 400


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
    user = _create_verified_user(
        username="inactive-refresh-user",
        email="inactive-refresh@example.com",
    )

    refresh_token = _login_and_get_refresh(
        api_client,
        identifier="inactive-refresh-user",
    )

    user.is_active = False
    user.save(update_fields=["is_active"])

    response = api_client.post(
        API_REFRESH_URL,
        {"refresh": refresh_token},
        format="json",
    )

    assert response.status_code == 400