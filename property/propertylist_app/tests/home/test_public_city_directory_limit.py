import pytest

from propertylist_app.api.views.public_locations import PUBLIC_CITY_DIRECTORY_SLUGS
from propertylist_app.models import City


CITIES_URL = "/api/v1/cities/"


@pytest.mark.django_db
def test_public_city_directory_is_limited_to_curated_twenty_without_deleting_catalogue(
    api_client,
):
    City.objects.all().delete()

    for display_order, slug in enumerate(PUBLIC_CITY_DIRECTORY_SLUGS):
        City.objects.create(
            name=slug.replace("-", " ").title(),
            slug=slug,
            is_active=True,
            display_order=display_order,
        )

    hidden = City.objects.create(
        name="Portsmouth",
        slug="portsmouth",
        is_active=True,
        display_order=999,
    )

    response = api_client.get(CITIES_URL, {"limit": 100})

    assert response.status_code == 200
    assert response.data["count"] == 20
    assert len(response.data["data"]) == 20
    assert {city["slug"] for city in response.data["data"]} == set(
        PUBLIC_CITY_DIRECTORY_SLUGS
    )

    # The city is hidden from the public directory, not deleted/deactivated.
    hidden.refresh_from_db()
    assert hidden.is_active is True
    assert City.objects.filter(pk=hidden.pk).exists()


@pytest.mark.django_db
def test_public_city_directory_search_cannot_expose_non_curated_city(api_client):
    City.objects.all().delete()
    City.objects.create(name="London", slug="london", is_active=True)
    City.objects.create(name="Portsmouth", slug="portsmouth", is_active=True)

    response = api_client.get(CITIES_URL, {"q": "Portsmouth", "limit": 100})

    assert response.status_code == 200
    assert response.data["count"] == 0
    assert response.data["data"] == []
