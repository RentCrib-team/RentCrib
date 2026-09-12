import json
from contextlib import nullcontext
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile

from property.celery_app import app as celery_app
from propertylist_app import city_image_tasks
from propertylist_app.services import city_image_autofill


class FakeResponse:
    def __init__(self, *, payload=None, content=b"", status_code=200):
        self._payload = payload
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeStorage:
    def __init__(self):
        self.files = {}

    def exists(self, name):
        return name in self.files

    def save(self, name, content):
        content.seek(0)
        self.files[name] = content.read()
        return name

    def delete(self, name):
        self.files.pop(name, None)


class FakeImageField:
    def __init__(self, storage, name=""):
        self.storage = storage
        self.name = name

    def __bool__(self):
        return bool(self.name)

    def save(self, name, content, save=False):
        content.seek(0)
        stored_name = f"city_images/{name}"
        self.storage.files[stored_name] = content.read()
        self.name = stored_name


class FakeCity:
    def __init__(self, *, pk, name, slug, storage, image_name="", image_alt=""):
        self.pk = pk
        self.name = name
        self.slug = slug
        self.is_active = True
        self.display_order = pk
        self.image = FakeImageField(storage, image_name)
        self.image_alt = image_alt
        self.saved_update_fields = None

    def save(self, *, update_fields):
        self.saved_update_fields = list(update_fields)


class FakeQuerySet:
    def __init__(self, cities):
        self.cities = cities

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *fields):
        return self

    def values_list(self, field, flat=False):
        assert field == "pk"
        assert flat is True
        return [city.pk for city in self.cities if city.is_active and not city.image]


class FakeManager:
    def __init__(self, cities):
        self.cities = {city.pk: city for city in cities}

    def filter(self, *args, **kwargs):
        return FakeQuerySet(list(self.cities.values()))

    def select_for_update(self):
        return self

    def get(self, *, pk):
        return self.cities[pk]


class FakeCityModel:
    objects = None


def _jpeg_bytes():
    handle = BytesIO()
    Image.new("RGB", (1800, 1200), "white").save(handle, "JPEG")
    return handle.getvalue()


def test_backend_automatically_populates_missing_city_images_and_preserves_existing_images():
    storage = FakeStorage()
    southampton = FakeCity(
        pk=1,
        name="Southampton",
        slug="southampton",
        storage=storage,
        image_name="city_images/southampton.webp",
        image_alt="Southampton city centre at night",
    )
    london = FakeCity(
        pk=2,
        name="London",
        slug="london",
        storage=storage,
    )
    FakeCityModel.objects = FakeManager([southampton, london])

    catalogue = (
        {
            "name": "Southampton",
            "display_name": "Southampton",
            "slug": "southampton",
            "nation": "England",
        },
        {
            "name": "London",
            "display_name": "London",
            "slug": "london",
            "nation": "England",
        },
    )

    image_bytes = _jpeg_bytes()
    requests_seen = []

    def fake_get(url, **kwargs):
        requests_seen.append((url, kwargs))
        if url == city_image_autofill.PEXELS_SEARCH_URL:
            assert kwargs["headers"] == {"Authorization": "test-key"}
            assert kwargs["params"]["query"] == (
                "London England United Kingdom city skyline"
            )
            return FakeResponse(
                payload={
                    "photos": [
                        {
                            "id": 987,
                            "photographer": "Example Photographer",
                            "url": "https://www.pexels.com/photo/london-view-987/",
                            "src": {
                                "large2x": "https://images.example/london.jpg",
                            },
                        }
                    ]
                }
            )
        if url == "https://images.example/london.jpg":
            return FakeResponse(content=image_bytes)
        raise AssertionError(f"unexpected request: {url}")

    def fake_prepare_image(uploaded):
        uploaded.seek(0)
        with Image.open(uploaded) as image:
            assert image.size == (1600, 900)
        uploaded.seek(0)
        return SimpleUploadedFile(
            "london.webp",
            uploaded.read(),
            content_type="image/webp",
        )

    result = city_image_autofill.autofill_missing_city_images(
        limit=5,
        api_key="test-key",
        http_get=fake_get,
        city_model=FakeCityModel,
        catalogue=catalogue,
        prepare_image=fake_prepare_image,
        atomic_context=nullcontext,
    )

    assert result == {
        "status": "ok",
        "attempted": 1,
        "imported": 1,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }

    assert southampton.image.name == "city_images/southampton.webp"
    assert southampton.image_alt == "Southampton city centre at night"

    assert london.image.name == "city_images/london.webp"
    assert london.image_alt == "London city view"
    assert london.saved_update_fields == ["image", "image_alt", "updated_at"]

    provenance_name = "city_image_provenance/london.json"
    assert provenance_name in storage.files
    provenance = json.loads(storage.files[provenance_name].decode("utf-8"))
    assert provenance["city_slug"] == "london"
    assert provenance["provider"] == "Pexels"
    assert provenance["provider_photo_id"] == "987"
    assert provenance["photographer"] == "Example Photographer"
    assert provenance["source_url"] == "https://www.pexels.com/photo/london-view-987/"
    assert provenance["license_name"] == "Pexels License"
    assert provenance["license_url"] == "https://www.pexels.com/license/"
    assert provenance["rights_confirmed"] is True
    assert provenance["stored_image"] == "city_images/london.webp"

    assert [url for url, _ in requests_seen] == [
        city_image_autofill.PEXELS_SEARCH_URL,
        "https://images.example/london.jpg",
    ]

    schedule = celery_app.conf.beat_schedule["autofill-missing-city-images"]
    assert schedule["task"] == "propertylist_app.autofill_missing_city_images"
    assert city_image_tasks.task_autofill_missing_city_images.name == (
        "propertylist_app.autofill_missing_city_images"
    )
