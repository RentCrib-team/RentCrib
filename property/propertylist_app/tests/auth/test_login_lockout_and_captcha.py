# property/propertylist_app/tests/auth/test_login_lockout_and_captcha.py

import pytest
from django.contrib.auth.models import User
from django.core.cache import caches
from django.urls import reverse
from rest_framework.settings import api_settings
from rest_framework.test import APIClient

from propertylist_app.models import UserProfile


def _ip_headers(ip="203.0.113.55"):
    # Fixed test IP so lockout/throttle keys are deterministic
    return {"REMOTE_ADDR": ip, "HTTP_X_FORWARDED_FOR": ip}


@pytest.mark.django_db
def test_login_lockout_after_repeated_failures(settings):
    # Clear any leftover throttle / lockout counters
    caches["default"].clear()

    # This test is about your custom "lockout after N bad passwords".
    # DRF's request-rate throttling must not trigger first.
    settings.REST_FRAMEWORK.setdefault("DEFAULT_THROTTLE_RATES", {})
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] = "10000/hour"
    api_settings.reload()

    settings.LOGIN_FAIL_LIMIT = 3
    settings.LOGIN_LOCKOUT_SECONDS = 600
    settings.TURNSTILE_REQUIRED = False

    user = User.objects.create_user(
        username="lockuser",
        password="pass12345",
        email="l@example.com",
    )
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": True})

    client = APIClient()
    url = reverse("v1:auth-login")

    # Fail N times -> must be 400 each time (invalid creds)
    for _ in range(settings.LOGIN_FAIL_LIMIT):
        r = client.post(
            url,
            {"identifier": "lockuser", "password": "WRONG"},
            format="json",
            **_ip_headers(),
        )
        assert r.status_code == 400, getattr(r, "data", r.content)

    # Next attempt -> must be locked out by your lockout logic (429)
    r_locked = client.post(
        url,
        {"identifier": "lockuser", "password": "WRONG"},
        format="json",
        **_ip_headers(),
    )
    assert r_locked.status_code == 429, getattr(r_locked, "data", r_locked.content)


@pytest.mark.django_db
def test_login_requires_turnstile_when_enabled(settings, monkeypatch):
    caches["default"].clear()

    settings.TURNSTILE_REQUIRED = True
    settings.LOGIN_FAIL_LIMIT = 10
    settings.LOGIN_LOCKOUT_SECONDS = 600

    # Avoid DRF throttling interfering with this Turnstile behaviour test.
    settings.REST_FRAMEWORK.setdefault("DEFAULT_THROTTLE_RATES", {})
    settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"] = "10000/hour"
    api_settings.reload()

    user = User.objects.create_user(
        username="catuser",
        password="pass12345",
        email="c@example.com",
    )
    UserProfile.objects.update_or_create(
        user=user,
        defaults={"email_verified": True},
    )

    client = APIClient()
    url = reverse("v1:auth-login")

    def fake_verify_fail(token, ip):
        return False

    monkeypatch.setattr(
        "propertylist_app.api.views.auth.verify_turnstile",
        fake_verify_fail,
    )

    r_bad = client.post(
        url,
        {
            "identifier": "catuser",
            "password": "pass12345",
            "turnstile_token": "token123",
        },
        format="json",
        **_ip_headers(),
    )

    assert r_bad.status_code == 400, r_bad.data
    assert "Security check failed" in str(r_bad.data)

    def fake_verify_ok(token, ip):
        return True

    monkeypatch.setattr(
        "propertylist_app.api.views.auth.verify_turnstile",
        fake_verify_ok,
    )

    r_ok = client.post(
        url,
        {
            "identifier": "catuser",
            "password": "pass12345",
            "turnstile_token": "token123",
        },
        format="json",
        **_ip_headers(),
    )

    assert r_ok.status_code == 200, r_ok.data
    assert r_ok.data.get("ok") is True
    assert "tokens" in r_ok.data.get("data", {})
    assert "access" in r_ok.data["data"]["tokens"]
    assert "refresh" in r_ok.data["data"]["tokens"]
    
    
@pytest.mark.django_db
def test_login_duplicate_email_returns_controlled_error_not_500(
    settings,
    monkeypatch,
):
    """
    Defensive regression test for legacy/corrupt duplicate-email data.

    The database now prevents creation of new case-insensitive duplicate
    emails, so simulate two legacy matching users at the queryset boundary
    and prove login returns account_conflict instead of HTTP 500.
    """
    caches["default"].clear()

    settings.TURNSTILE_REQUIRED = False
    settings.LOGIN_FAIL_LIMIT = 10
    settings.LOGIN_LOCKOUT_SECONDS = 600

    settings.REST_FRAMEWORK.setdefault(
        "DEFAULT_THROTTLE_RATES",
        {},
    )
    settings.REST_FRAMEWORK[
        "DEFAULT_THROTTLE_RATES"
    ]["login"] = "10000/hour"
    api_settings.reload()

    UserModel = User

    original_filter = UserModel.objects.filter

    class DuplicateEmailQuery:
        def order_by(self, *args, **kwargs):
            return self

        def __getitem__(self, key):
            if isinstance(key, slice):
                return [
                    type(
                        "LegacyUser",
                        (),
                        {"id": 101},
                    )(),
                    type(
                        "LegacyUser",
                        (),
                        {"id": 202},
                    )(),
                ]

            raise IndexError(key)

    def duplicate_email_filter(*args, **kwargs):
        if "email__iexact" in kwargs:
            return DuplicateEmailQuery()

        return original_filter(*args, **kwargs)

    monkeypatch.setattr(
        UserModel.objects,
        "filter",
        duplicate_email_filter,
    )

    client = APIClient()
    url = reverse("v1:auth-login")

    response = client.post(
        url,
        {
            "identifier": "duplicate-login@example.com",
            "password": "pass12345",
        },
        format="json",
        **_ip_headers("203.0.113.77"),
    )

    assert response.status_code == 400, getattr(
        response,
        "data",
        response.content,
    )

    assert response.data["ok"] is False
    assert response.data["code"] == "account_conflict"

    assert (
        "contact support"
        in response.data["message"].lower()
    )
    
    
@pytest.mark.django_db(transaction=True)
def test_database_rejects_case_insensitive_duplicate_email():
    from django.db import IntegrityError, transaction

    User.objects.create_user(
        username="email_unique_one",
        email="CaseSensitive@TestExample.com",
        password="pass12345",
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(
                username="email_unique_two",
                email="casesensitive@testexample.com",
                password="pass12345",
            )        