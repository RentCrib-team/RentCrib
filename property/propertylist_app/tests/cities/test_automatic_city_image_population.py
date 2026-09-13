import json
from contextlib import nullcontext
from io import BytesIO

import celery_app as runtime_celery_app
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile

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


def test_backend_populates_missing_city_images_from_pexels_without_attribution_strip():
    storage = FakeStorage()
    southampton = FakeCity(
        pk=1,
        name="Southampton",
        slug="southampton",
        storage=storage,
        image_name="city_images/southampton.webp",
        image_alt="Southampton city centre at night",
    )
    london = FakeCity(pk=2, name="London", slug="london", storage=storage)
    manchester = FakeCity(pk=3, name="Manchester", slug="manchester", storage=storage)
    FakeCityModel.objects = FakeManager([southampton, london, manchester])

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
        {
            "name": "Manchester",
            "display_name": "Manchester",
            "slug": "manchester",
            "nation": "England",
        },
    )

    requests_seen = []
    image_bytes = _jpeg_bytes()
    irrelevant_url = "https://images.pexels.example/generic.jpeg"
    relevant_url = "https://images.pexels.example/london.jpeg"

    def fake_get(url, **kwargs):
        requests_seen.append((url, kwargs))
        if url == city_image_autofill.PEXELS_SEARCH_URL:
            params = kwargs["params"]
            assert kwargs["headers"] == {"Authorization": "test-pexels-key"}
            assert params["orientation"] == "landscape"
            assert params["size"] == "large"
            assert params["per_page"] == 15
            assert params["page"] == 1
            query = params["query"]
            assert query in {
                "London England United Kingdom city skyline",
                "London England United Kingdom city centre",
                "London England United Kingdom landmark",
            }
            return FakeResponse(
                payload={
                    "photos": [
                        {
                            "id": 999,
                            "photographer": "Generic Photographer",
                            "url": "https://www.pexels.com/photo/999/",
                            "alt": "Portrait of a person outdoors",
                            "width": 1800,
                            "height": 1200,
                            "src": {"large2x": irrelevant_url},
                        },
                        {
                            "id": 12345,
                            "photographer": "Example Photographer",
                            "url": "https://www.pexels.com/photo/london-city-skyline-12345/",
                            "alt": "London city skyline and architecture",
                            "width": 2400,
                            "height": 1350,
                            "src": {"large2x": relevant_url},
                        },
                    ]
                }
            )
        if url == relevant_url:
            return FakeResponse(content=image_bytes)
        if url == irrelevant_url:
            raise AssertionError("irrelevant first Pexels result must not be downloaded")
        raise AssertionError(f"unexpected request: {url}")

    def fake_prepare_image(uploaded):
        uploaded.seek(0)
        with Image.open(uploaded) as image:
            assert image.size == (1600, 900)
            assert image.getpixel((1, 899))[0] > 240
            assert image.getpixel((1, 899))[1] > 240
            assert image.getpixel((1, 899))[2] > 240
        uploaded.seek(0)
        return SimpleUploadedFile(
            "london.webp",
            uploaded.read(),
            content_type="image/webp",
        )

    result = city_image_autofill.autofill_city_image(
        2,
        api_key="test-pexels-key",
        http_get=fake_get,
        city_model=FakeCityModel,
        catalogue=catalogue,
        prepare_image=fake_prepare_image,
        atomic_context=nullcontext,
    )

    assert result["status"] == "imported"
    assert result["slug"] == "london"
    assert southampton.image.name == "city_images/southampton.webp"
    assert london.image.name == "city_images/london.webp"
    assert london.image_alt == "London city view"
    assert london.saved_update_fields == ["image", "image_alt", "updated_at"]

    provenance_name = "city_image_provenance/london.json"
    assert provenance_name in storage.files
    provenance = json.loads(storage.files[provenance_name].decode("utf-8"))
    assert provenance["provider"] == "Pexels"
    assert provenance["provider_photo_id"] == "12345"
    assert provenance["license_name"] == "Pexels License"
    assert provenance["photographer"] == "Example Photographer"
    assert provenance["relevance_score"] > 0
    assert provenance["stored_image"] == "city_images/london.webp"

    queued = []
    queue_result = city_image_tasks.enqueue_missing_city_images(
        city_model=FakeCityModel,
        enqueue=queued.append,
    )
    assert queue_result == {"queued": 1, "city_ids": [3]}
    assert queued == [3]

    runtime_celery_app.app.finalize()
    runtime_schedule = runtime_celery_app.app.conf.beat_schedule[
        "autofill-missing-city-images"
    ]
    assert runtime_schedule["task"] == "propertylist_app.enqueue_missing_city_images"
    assert "propertylist_app.city_image_tasks" in tuple(
        runtime_celery_app.app.conf.imports
    )
    assert city_image_tasks.task_autofill_city_image.name == (
        "propertylist_app.autofill_city_image"
    )
    assert city_image_tasks.task_enqueue_missing_city_images.name == (
        "propertylist_app.enqueue_missing_city_images"
    )

    search_requests = [
        kwargs["params"]["query"]
        for url, kwargs in requests_seen
        if url == city_image_autofill.PEXELS_SEARCH_URL
    ]
    assert search_requests == [
        "London England United Kingdom city skyline",
        "London England United Kingdom city centre",
        "London England United Kingdom landmark",
    ]
    assert [url for url, _ in requests_seen if url != city_image_autofill.PEXELS_SEARCH_URL] == [
        relevant_url,
    ]
