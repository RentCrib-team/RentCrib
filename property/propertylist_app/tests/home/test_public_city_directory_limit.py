import pytest

from propertylist_app.api.views.public_locations import (
    HOMEPAGE_POPULAR_CITY_SLUGS,
    PUBLIC_CITY_DIRECTORY_SLUGS,
)
from propertylist_app.models import City


CITIES_URL = "/api/v1/cities/"
HOME_URL = "/api/v1/home/"


EXPECTED_PUBLIC_CITY_SLUGS = (
    "london",
    "birmingham",
    "glasgow",
    "leeds",
    "edinburgh",
    "liverpool",
    "sheffield",
    "manchester",
    "bristol",
    "leicester",
    "cardiff",
    "belfast",
    "coventry",
    "bradford",
    "nottingham",
    "newcastle-upon-tyne",
    "brighton-hove",
    "derby",
    "kingston-upon-hull",
    "plymouth",
)


@pytest.mark.django_db
def test_public_city_directory_is_exact_population_ranked_twenty_without_deleting_catalogue(
    api_client,
):
    City.objects.all().delete()

    assert PUBLIC_CITY_DIRECTORY_SLUGS == EXPECTED_PUBLIC_CITY_SLUGS

    for reverse_order, slug in enumerate(reversed(PUBLIC_CITY_DIRECTORY_SLUGS)):
        City.objects.create(
            name=slug.replace("-", " ").title(),
            slug=slug,
            is_active=True,
            is_featured=False,
            display_order=reverse_order,
        )

    hidden = City.objects.create(
        name="Southampton",
        slug="southampton",
        is_active=True,
        is_featured=True,
        display_order=999,
    )

    response = api_client.get(CITIES_URL, {"limit": 100})

    assert response.status_code == 200
    assert response.data["count"] == 20
    assert [city["slug"] for city in response.data["data"]] == list(
        EXPECTED_PUBLIC_CITY_SLUGS
    )

    hidden.refresh_from_db()
    assert hidden.is_active is True
    assert City.objects.filter(pk=hidden.pk).exists()


@pytest.mark.django_db
def test_homepage_popular_cities_are_first_twelve_population_ranked_public_cities(
    api_client,
):
    City.objects.all().delete()

    assert HOMEPAGE_POPULAR_CITY_SLUGS == EXPECTED_PUBLIC_CITY_SLUGS[:12]

    for reverse_order, slug in enumerate(reversed(PUBLIC_CITY_DIRECTORY_SLUGS)):
        City.objects.create(
            name=slug.replace("-", " ").title(),
            slug=slug,
            is_active=True,
            is_featured=False,
            display_order=reverse_order,
        )

    City.objects.create(
        name="Southampton",
        slug="southampton",
        is_active=True,
        is_featured=True,
        display_order=-1,
    )

    response = api_client.get(HOME_URL)

    assert response.status_code == 200
    assert [
        city["slug"] for city in response.data["data"]["popular_cities"]
    ] == list(EXPECTED_PUBLIC_CITY_SLUGS[:12])


@pytest.mark.django_db
def test_public_city_directory_search_cannot_expose_non_public_city(api_client):
    City.objects.all().delete()
    City.objects.create(name="London", slug="london", is_active=True)
    City.objects.create(name="Southampton", slug="southampton", is_active=True)

    response = api_client.get(CITIES_URL, {"q": "Southampton", "limit": 100})

    assert response.status_code == 200
    assert response.data["count"] == 0
    assert response.data["data"] == []
