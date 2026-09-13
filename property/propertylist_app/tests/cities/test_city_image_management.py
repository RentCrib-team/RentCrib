from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from propertylist_app.models import City


ADMIN_CITIES_URL = "/api/v1/admin/locations/cities/"
PUBLIC_CITIES_URL = "/api/v1/cities/"
FALLBACK_SUFFIX = "/static/propertylist_app/city-card-fallback.svg"


def _set_admin_role(user, role="ops_admin"):
    profile = user.profile
    profile.admin_role = role
    profile.save(update_fields=["admin_role"])
    return user


def _image_upload(name="city.jpg", *, width=1600, height=900):
    output = BytesIO()
    Image.new("RGB", (width, height), (120, 135, 150)).save(
        output,
        format="JPEG",
        quality=90,
    )
    return SimpleUploadedFile(
        name,
        output.getvalue(),
        content_type="image/jpeg",
    )


@pytest.mark.django_db
def test_public_city_without_upload_uses_backend_fallback(api_client):
    City.objects.all().delete()
    City.objects.create(name="Southampton", is_active=True)

    response = api_client.get(
        PUBLIC_CITIES_URL,
        {"q": "Southampton", "limit": 100},
    )

    assert response.status_code == 200
    city = response.data["data"][0]
    assert city["name"] == "Southampton"
    assert city["image"] is None
    assert city["has_image"] is False
    assert city["image_url"].endswith(FALLBACK_SUFFIX)


@pytest.mark.django_db(transaction=True)
def test_ops_admin_can_upload_filter_and_clear_city_image(
    api_client,
    user_factory,
):
    City.objects.all().delete()
    southampton = City.objects.create(name="Southampton", is_active=True)
    City.objects.create(name="Bristol", is_active=True)

    user = _set_admin_role(
        user_factory(username="ops-city-image", is_staff=True),
    )
    api_client.force_authenticate(user=user)

    upload_response = api_client.patch(
        f"{ADMIN_CITIES_URL}{southampton.id}/",
        {
            "image": _image_upload(),
            "image_alt": "Southampton waterfront skyline",
        },
        format="multipart",
    )

    assert upload_response.status_code == 200, upload_response.data
    assert upload_response.data["data"]["has_image"] is True
    assert not upload_response.data["data"]["image_url"].endswith(FALLBACK_SUFFIX)
    assert upload_response.data["data"]["image_alt"] == "Southampton waterfront skyline"

    southampton.refresh_from_db()
    old_image_name = southampton.image.name
    old_storage = southampton.image.storage
    assert old_image_name

    missing_response = api_client.get(
        ADMIN_CITIES_URL,
        {"has_image": "false"},
    )
    assert missing_response.status_code == 200
    assert [
        city["name"] for city in missing_response.data["data"]["results"]
    ] == ["Bristol"]

    clear_response = api_client.patch(
        f"{ADMIN_CITIES_URL}{southampton.id}/",
        {"image": None},
        format="json",
    )
    assert clear_response.status_code == 200, clear_response.data
    assert clear_response.data["data"]["has_image"] is False
    assert clear_response.data["data"]["image_url"].endswith(FALLBACK_SUFFIX)
    assert not old_storage.exists(old_image_name)


@pytest.mark.django_db
def test_admin_rejects_city_image_below_card_minimum(
    api_client,
    user_factory,
):
    City.objects.all().delete()
    city = City.objects.create(name="Manchester", is_active=True)

    user = _set_admin_role(
        user_factory(username="ops-city-small-image", is_staff=True),
    )
    api_client.force_authenticate(user=user)

    response = api_client.patch(
        f"{ADMIN_CITIES_URL}{city.id}/",
        {"image": _image_upload(width=320, height=180)},
        format="multipart",
    )

    assert response.status_code == 400
    city.refresh_from_db()
    assert not city.image


@pytest.mark.django_db
def test_admin_rejects_portrait_city_card_image(
    api_client,
    user_factory,
):
    City.objects.all().delete()
    city = City.objects.create(name="Leeds", is_active=True)

    user = _set_admin_role(
        user_factory(username="ops-city-portrait-image", is_staff=True),
    )
    api_client.force_authenticate(user=user)

    response = api_client.patch(
        f"{ADMIN_CITIES_URL}{city.id}/",
        {"image": _image_upload(width=800, height=1000)},
        format="multipart",
    )

    assert response.status_code == 400
    city.refresh_from_db()
    assert not city.image
