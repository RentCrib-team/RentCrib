import pytest


@pytest.mark.django_db
def test_every_response_has_request_id(client):
    response = client.get(
        "/health/",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"]


@pytest.mark.django_db
def test_client_request_id_is_preserved(client):
    response = client.get(
        "/health/",
        HTTP_HOST="localhost",
        HTTP_X_REQUEST_ID="bug20-test-correlation",
    )

    assert response.status_code == 200
    assert (
        response.headers["X-Request-ID"]
        == "bug20-test-correlation"
    )


@pytest.mark.django_db
def test_every_response_has_backend_timing(client):
    response = client.get(
        "/health/",
        HTTP_HOST="localhost",
    )

    assert response.status_code == 200

    backend_timing = response.headers.get(
        "X-Backend-Response-Time-Ms"
    )
    legacy_timing = response.headers.get(
        "X-Response-Time-ms"
    )

    assert backend_timing is not None
    assert legacy_timing is not None
    assert float(backend_timing) >= 0
    assert float(legacy_timing) >= 0
    assert backend_timing == legacy_timing