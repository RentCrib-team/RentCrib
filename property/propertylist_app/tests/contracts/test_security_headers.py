from django.test import override_settings


def test_health_response_has_content_security_policy(client):
    response = client.get("/health/")

    assert response.status_code == 200

    policy = response.headers.get("Content-Security-Policy")

    assert policy
    assert "default-src 'self'" in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy


def test_health_response_has_permissions_policy(client):
    response = client.get("/health/")

    assert response.status_code == 200

    policy = response.headers.get("Permissions-Policy")

    assert policy
    assert "camera=()" in policy
    assert "microphone=()" in policy
    assert "geolocation=()" in policy


@override_settings(
    SECURE_HSTS_SECONDS=31536000,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
)
def test_secure_response_has_one_year_hsts(client):
    response = client.get("/health/", secure=True)

    assert response.status_code == 200

    hsts = response.headers.get("Strict-Transport-Security")

    assert hsts
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts


def test_swagger_ui_remains_available_with_security_headers(client):
    response = client.get("/api/v1/schema/swagger-ui/")

    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    assert "Permissions-Policy" in response.headers


def test_redoc_remains_available_with_security_headers(client):
    response = client.get("/api/v1/schema/redoc/")

    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    assert "Permissions-Policy" in response.headers