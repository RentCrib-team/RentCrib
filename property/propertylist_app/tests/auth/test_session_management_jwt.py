import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from propertylist_app.models import UserProfile


def create_verified_user(django_user_model, *, username, email):
    user = django_user_model.objects.create_user(
        username=username,
        email=email,
        password="pass1234",
    )

    UserProfile.objects.update_or_create(
        user=user,
        defaults={"email_verified": True},
    )

    return user


@pytest.mark.django_db
def test_logout_blacklists_refresh_token_without_access_token(
    api_client,
    django_user_model,
):
    create_verified_user(
        django_user_model,
        username="bob",
        email="bob@example.com",
    )

    login_url = reverse("v1:auth-login")
    logout_url = reverse("v1:auth-logout")
    refresh_url = reverse("v1:auth-token-refresh")

    login_response = api_client.post(
        login_url,
        {
            "identifier": "bob",
            "password": "pass1234",
        },
        format="json",
    )

    assert login_response.status_code == status.HTTP_200_OK
    refresh = login_response.data["data"]["tokens"]["refresh"]

    # Deliberately send no access-token Authorization header.
    logout_response = api_client.post(
        logout_url,
        {"refresh": refresh},
        format="json",
    )

    assert logout_response.status_code == status.HTTP_200_OK
    assert logout_response.data["ok"] is True

    refresh_response = api_client.post(
        refresh_url,
        {"refresh": refresh},
        format="json",
    )

    assert refresh_response.status_code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED,
    )


@pytest.mark.django_db
def test_logout_rejects_missing_refresh_token(api_client):
    logout_url = reverse("v1:auth-logout")

    response = api_client.post(
        logout_url,
        {},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "refresh" in str(response.data).lower()


@pytest.mark.django_db
def test_logout_rejects_malformed_refresh_token(api_client):
    logout_url = reverse("v1:auth-logout")

    response = api_client.post(
        logout_url,
        {"refresh": "not-a-valid-jwt"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "refresh" in str(response.data).lower()


@pytest.mark.django_db
def test_blacklisted_refresh_token_cannot_logout_twice(
    api_client,
    django_user_model,
):
    user = create_verified_user(
        django_user_model,
        username="kate",
        email="kate@example.com",
    )

    refresh = str(RefreshToken.for_user(user))
    logout_url = reverse("v1:auth-logout")

    first_response = api_client.post(
        logout_url,
        {"refresh": refresh},
        format="json",
    )

    assert first_response.status_code == status.HTTP_200_OK

    second_response = api_client.post(
        logout_url,
        {"refresh": refresh},
        format="json",
    )

    assert second_response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_logout_rejects_refresh_token_for_inactive_user(
    api_client,
    django_user_model,
):
    user = create_verified_user(
        django_user_model,
        username="inactive-user",
        email="inactive@example.com",
    )

    refresh = str(RefreshToken.for_user(user))

    user.is_active = False
    user.save(update_fields=["is_active"])

    logout_url = reverse("v1:auth-logout")

    response = api_client.post(
        logout_url,
        {"refresh": refresh},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST