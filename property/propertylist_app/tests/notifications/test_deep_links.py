from django.test import override_settings

from propertylist_app.services.deep_links import (
    build_absolute_url,
)


@override_settings(
    FRONTEND_BASE_URL="https://rentcrib.example"
)
def test_build_absolute_url_direct_when_force_login_false():
    url = build_absolute_url(
        "/app/tenancies/123",
        force_login=False,
    )

    assert (
        url
        == "https://rentcrib.example/app/tenancies/123"
    )
    assert "/login?next=" not in url


@override_settings(
    FRONTEND_BASE_URL="https://rentcrib.example"
)
def test_build_absolute_url_direct_when_force_login_true():
    url = build_absolute_url(
        "/app/tenancies/123",
        force_login=True,
    )

    assert (
        url
        == "https://rentcrib.example/app/tenancies/123"
    )
    assert "/login?next=" not in url


@override_settings(
    FRONTEND_BASE_URL="https://rentcrib.example/"
)
def test_build_absolute_url_handles_trailing_base_slash():
    url = build_absolute_url(
        "/app/threads/72",
        force_login=True,
    )

    assert (
        url
        == "https://rentcrib.example/app/threads/72"
    )


@override_settings(
    FRONTEND_BASE_URL="https://rentcrib.example"
)
def test_build_absolute_url_rejects_unsafe_external_path():
    url = build_absolute_url(
        "https://evil.example/phishing",
        force_login=True,
    )

    assert url == "https://rentcrib.example/messages"