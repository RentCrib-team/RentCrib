import pytest
from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie


def live_paid_until():
    return timezone.now().date() + timedelta(days=30)


@pytest.mark.django_db
def test_text_and_price_filters():
    """
    /api/search/rooms/?q=&min_price=&max_price=
    Ensures text search and price range both filter results.
    """
    owner = User.objects.create_user(username="owner", password="pass123")
    cat = RoomCategorie.objects.create(name="General", active=True)

    Room.objects.create(
        title="Cozy flat in London",
        description="Nice and clean near station",
        price_per_month=900,
        location="London SW1A 1AA",
        category=cat,
        property_owner=owner,
        paid_until=live_paid_until(),
    )
    Room.objects.create(
        title="Luxury apartment",
        description="Spacious apartment in Birmingham",
        price_per_month=2000,
        location="Birmingham B1 1AA",
        category=cat,
        property_owner=owner,
        paid_until=live_paid_until(),
    )

    client = APIClient()
    url = reverse("v1:search-rooms")

    # Text filter
    r1 = client.get(url, {"q": "cozy"})
    assert r1.status_code == 200
    titles1 = [it["title"].lower() for it in r1.json().get("results", r1.json())]
    assert any("cozy" in t for t in titles1)
    assert all("luxury" not in t for t in titles1)

    # Price range filter
    r2 = client.get(url, {"min_price": 800, "max_price": 1000})
    assert r2.status_code == 200
    titles2 = [it["title"] for it in r2.json().get("results", r2.json())]

    assert "Cozy flat in London" in titles2
    assert "Luxury apartment" not in titles2


@pytest.mark.django_db
def test_ordering_by_created_and_price():
    """
    /api/search/rooms/?ordering=created_at | -created_at | price_per_month | -price_per_month
    """
    owner = User.objects.create_user(username="o2", password="pass123")
    cat = RoomCategorie.objects.create(name="Cat", active=True)

    Room.objects.create(
        title="A",
        description="..",
        price_per_month=500,
        location="London",
        category=cat,
        property_owner=owner,
        paid_until=live_paid_until(),
    )
    Room.objects.create(
        title="B",
        description="..",
        price_per_month=800,
        location="London",
        category=cat,
        property_owner=owner,
        paid_until=live_paid_until(),
    )

    client = APIClient()
    url = reverse("v1:search-rooms")

    # created_at descending: latest first
    rd = client.get(url, {"ordering": "-created_at"})
    assert rd.status_code == 200
    titles_desc = [it["title"] for it in rd.json().get("results", rd.json())]
    assert titles_desc.index("B") < titles_desc.index("A")

    # price ascending
    rp = client.get(url, {"ordering": "price_per_month"})
    assert rp.status_code == 200
    titles_price = [it["title"] for it in rp.json().get("results", rp.json())]
    assert titles_price.index("A") < titles_price.index("B")

    # price descending
    rpd = client.get(url, {"ordering": "-price_per_month"})
    assert rpd.status_code == 200
    titles_price_desc = [it["title"] for it in rpd.json().get("results", rpd.json())]
    assert titles_price_desc.index("B") < titles_price_desc.index("A")


@pytest.mark.django_db
def test_requires_postcode_when_radius_provided():
    """
    /api/search/rooms/?radius_miles=10 requires postcode.
    """
    client = APIClient()
    url = reverse("v1:search-rooms")

    r = client.get(url, {"radius_miles": 10})

    assert r.status_code == 400
    assert r.data.get("ok") is False
    assert "postcode" in r.data.get("field_errors", {})


@pytest.mark.django_db
def test_pagination_limit_works():
    """
    Basic sanity: limit controls number of items in page.
    """
    owner = User.objects.create_user(username="o4", password="pass123")
    cat = RoomCategorie.objects.create(name="Pag", active=True)

    for i in range(6):
        Room.objects.create(
            title=f"R{i}",
            description="..",
            price_per_month=600 + i,
            location="Leeds LS1 1AA",
            category=cat,
            property_owner=owner,
            paid_until=live_paid_until(),
        )

    client = APIClient()
    url = reverse("v1:search-rooms")

    r = client.get(url, {"limit": 2})
    assert r.status_code == 200
    data = r.json()
    results = data.get("results", data)

    assert len(results) == 2