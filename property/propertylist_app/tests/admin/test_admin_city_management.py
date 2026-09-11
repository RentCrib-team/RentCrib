import pytest

from propertylist_app.models import City


ADMIN_CITIES_URL = "/api/v1/admin/locations/cities/"


def _set_admin_role(user, role):
    profile = user.profile
    profile.admin_role = role
    profile.save(update_fields=["admin_role"])
    return user


@pytest.mark.django_db
def test_ops_admin_can_create_city(api_client, user_factory):
    user = _set_admin_role(
        user_factory(username="ops-city-admin"),
        "ops_admin",
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        ADMIN_CITIES_URL,
        {
            "name": "Southampton",
            "is_active": True,
            "is_featured": True,
            "display_order": 1,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["data"]["name"] == "Southampton"
    assert response.data["data"]["slug"] == "southampton"
    assert response.data["data"]["image_alt"] == "Southampton"
    assert response.data["data"]["is_featured"] is True
    assert City.objects.filter(name="Southampton").exists()


@pytest.mark.django_db
def test_non_ops_admin_cannot_manage_cities(api_client, user_factory):
    user = _set_admin_role(
        user_factory(username="support-city-admin"),
        "support_admin",
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        ADMIN_CITIES_URL,
        {"name": "Manchester"},
        format="json",
    )

    assert response.status_code == 403
    assert not City.objects.filter(name="Manchester").exists()


@pytest.mark.django_db
def test_city_names_are_unique_case_insensitively(api_client, user_factory):
    City.objects.create(name="London")
    user = _set_admin_role(
        user_factory(username="ops-city-duplicate"),
        "ops_admin",
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        ADMIN_CITIES_URL,
        {"name": "london"},
        format="json",
    )

    assert response.status_code == 400
    assert City.objects.filter(name__iexact="london").count() == 1


@pytest.mark.django_db
def test_admin_city_list_filters_featured_and_orders_by_display_order(
    api_client,
    user_factory,
):
    City.objects.create(
        name="Leeds",
        is_featured=True,
        display_order=2,
    )
    City.objects.create(
        name="Southampton",
        is_featured=True,
        display_order=1,
    )
    City.objects.create(
        name="Canterbury",
        is_featured=False,
        display_order=0,
    )

    user = _set_admin_role(
        user_factory(username="ops-city-list"),
        "ops_admin",
    )
    api_client.force_authenticate(user=user)

    response = api_client.get(
        ADMIN_CITIES_URL,
        {"is_featured": "true"},
    )

    assert response.status_code == 200
    assert response.data["data"]["total_results"] == 2
    assert [
        city["name"] for city in response.data["data"]["results"]
    ] == ["Southampton", "Leeds"]


@pytest.mark.django_db
def test_ops_admin_can_update_city_controls(api_client, user_factory):
    city = City.objects.create(
        name="Bristol",
        is_active=True,
        is_featured=False,
        display_order=0,
    )
    user = _set_admin_role(
        user_factory(username="ops-city-update"),
        "ops_admin",
    )
    api_client.force_authenticate(user=user)

    response = api_client.patch(
        f"{ADMIN_CITIES_URL}{city.id}/",
        {
            "is_active": False,
            "is_featured": True,
            "display_order": 4,
        },
        format="json",
    )

    assert response.status_code == 200
    city.refresh_from_db()
    assert city.is_active is False
    assert city.is_featured is True
    assert city.display_order == 4
