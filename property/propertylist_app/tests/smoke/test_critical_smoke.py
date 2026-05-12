import pytest
from django.urls import reverse
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def test_smoke_health_endpoint():
    client = APIClient()

    response = client.get(reverse("v1:health"))

    assert response.status_code == 200, response.json()
    assert response.json()["ok"] is True
    assert response.json()["data"]["status"] == "ok"


def test_smoke_public_search_endpoint():
    client = APIClient()

    response = client.get("/api/v1/search/rooms/")

    assert response.status_code == 200, response.json()
    assert response.json()["ok"] is True


def test_smoke_auth_login_rejects_invalid_credentials():
    client = APIClient()

    response = client.post(
        "/api/v1/auth/login/",
        {
            "identifier": "missing@example.com",
            "password": "WrongPass123!",
        },
        format="json",
    )

    assert response.status_code in (400, 401), response.json()
    assert response.json()["ok"] is False
    
    
    
    
    
    
    
    
    
    
    