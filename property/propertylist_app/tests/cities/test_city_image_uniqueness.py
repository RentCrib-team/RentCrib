import hashlib
import json
from contextlib import nullcontext
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile

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

    def open(self, name, mode="rb"):
        return BytesIO(self.files[name])


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
    def __init__(self, *, pk, name, slug, storage, image_name=""):
        self.pk = pk
        self.name = name
        self.slug = slug
        self.is_active = True
        self.image = FakeImageField(storage, image_name)
        self.image_alt = ""
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
        return [city.pk for city in self.cities if city.is_active]


class FakeManager:
    def __init__(self, cities):
        self.cities = {city.pk: city for city in cities}

    def select_for_update(self):
        return self

    def filter(self, *args, **kwargs):
        return FakeQuerySet(list(self.cities.values()))

    def get(self, *, pk):
        return self.cities[pk]


class FakeCityModel:
    objects = None


def _jpeg_bytes(colour):
    handle = BytesIO()
    Image.new("RGB", (1800, 1200), colour).save(handle, "JPEG")
    return handle.getvalue()


def _prepared_hash(source_bytes):
    uploaded = city_image_autofill._normalise_downloaded_image(
        content=source_bytes,
        slug="existing",
    )
    uploaded.seek(0)
    return hashlib.sha256(uploaded.read()).hexdigest()


def test_city_autofill_skips_photo_id_and_image_content_already_used_by_other_cities():
    storage = FakeStorage()
    birmingham = FakeCity(
        pk=1,
        name="Birmingham",
        slug="birmingham",
        storage=storage,
        image_name="city_images/birmingham.webp",
    )
    leeds = FakeCity(
        pk=2,
        name="Leeds",
        slug="leeds",
        storage=storage,
        image_name="city_images/leeds.webp",
    )
    london = FakeCity(pk=3, name="London", slug="london", storage=storage)
    FakeCityModel.objects = FakeManager([birmingham, leeds, london])

    duplicate_content = _jpeg_bytes("white")
    unique_content = _jpeg_bytes("black")

    storage.files["city_image_provenance/birmingham.json"] = json.dumps(
        {
            "provider": "Pexels",
            "provider_photo_id": "111",
            "stored_image": "city_images/birmingham.webp",
        }
    ).encode("utf-8")
    storage.files["city_image_provenance/leeds.json"] = json.dumps(
        {
            "provider": "Pexels",
            "provider_photo_id": "222",
            "content_sha256": _prepared_hash(duplicate_content),
            "stored_image": "city_images/leeds.webp",
        }
    ).encode("utf-8")

    catalogue = (
        {"name": "Birmingham", "display_name": "Birmingham", "slug": "birmingham", "nation": "England"},
        {"name": "Leeds", "display_name": "Leeds", "slug": "leeds", "nation": "England"},
        {"name": "London", "display_name": "London", "slug": "london", "nation": "England"},
    )

    used_id_url = "https://images.pexels.example/used-id.jpeg"
    duplicate_content_url = "https://images.pexels.example/duplicate-content.jpeg"
    unique_url = "https://images.pexels.example/unique.jpeg"
    downloads = []

    photos = [
        {
            "id": 111,
            "photographer": "Used ID",
            "url": "https://www.pexels.com/photo/111/",
            "alt": "London city skyline architecture",
            "width": 2400,
            "height": 1350,
            "src": {"large2x": used_id_url},
        },
        {
            "id": 333,
            "photographer": "Duplicate Content",
            "url": "https://www.pexels.com/photo/333/",
            "alt": "London city skyline architecture",
            "width": 2400,
            "height": 1350,
            "src": {"large2x": duplicate_content_url},
        },
        {
            "id": 444,
            "photographer": "Unique Content",
            "url": "https://www.pexels.com/photo/444/",
            "alt": "London city skyline architecture",
            "width": 2400,
            "height": 1350,
            "src": {"large2x": unique_url},
        },
    ]

    def fake_get(url, **kwargs):
        if url == city_image_autofill.PEXELS_SEARCH_URL:
            return FakeResponse(payload={"photos": photos})
        downloads.append(url)
        if url == used_id_url:
            raise AssertionError("a Pexels photo ID already used by another city must not be downloaded")
        if url == duplicate_content_url:
            return FakeResponse(content=duplicate_content)
        if url == unique_url:
            return FakeResponse(content=unique_content)
        raise AssertionError(f"unexpected request: {url}")

    def fake_prepare_image(uploaded):
        uploaded.seek(0)
        return SimpleUploadedFile(
            "london.jpg",
            uploaded.read(),
            content_type="image/jpeg",
        )

    result = city_image_autofill.autofill_city_image(
        london.pk,
        api_key="test-pexels-key",
        http_get=fake_get,
        city_model=FakeCityModel,
        catalogue=catalogue,
        prepare_image=fake_prepare_image,
        atomic_context=nullcontext,
    )

    assert result["status"] == "imported"
    assert downloads == [duplicate_content_url, unique_url]
    assert london.image.name == "city_images/london.jpg"

    provenance = json.loads(
        storage.files["city_image_provenance/london.json"].decode("utf-8")
    )
    assert provenance["provider_photo_id"] == "444"
    assert provenance["content_sha256"] == _prepared_hash(unique_content)
    assert provenance["time_preference"] == "night"
    assert "night" in provenance["search_query"]


def test_city_autofill_rotates_day_and_night_preferences_with_fallback_queries():
    storage = FakeStorage()
    night_city = FakeCity(pk=1, name="London", slug="london", storage=storage)
    day_city = FakeCity(pk=2, name="Leeds", slug="leeds", storage=storage)

    assert city_image_autofill._city_time_preference(night_city) == "night"
    assert city_image_autofill._city_time_preference(day_city) == "day"

    item = {
        "name": "London",
        "display_name": "London",
        "slug": "london",
        "nation": "England",
    }
    queries = city_image_autofill._search_queries(item)
    assert "London England United Kingdom city skyline" in queries
    assert "London England United Kingdom city centre" in queries
    assert "London England United Kingdom landmark" in queries
    assert "London England United Kingdom city skyline at night" in queries
    assert "London England United Kingdom city lights at night" in queries

    photo = {
        "id": 10,
        "alt": "London skyline architecture",
        "url": "https://www.pexels.com/photo/10/",
        "width": 2400,
        "height": 1350,
        "src": {"large2x": "https://images.pexels.example/10.jpeg"},
    }
    day_query = "London England United Kingdom city skyline"
    night_query = "London England United Kingdom city skyline at night"

    night_pref_night_score = city_image_autofill._photo_relevance_score(
        photo,
        item=item,
        query=night_query,
        preferred_time="night",
    )
    night_pref_day_score = city_image_autofill._photo_relevance_score(
        photo,
        item=item,
        query=day_query,
        preferred_time="night",
    )
    day_pref_day_score = city_image_autofill._photo_relevance_score(
        photo,
        item=item,
        query=day_query,
        preferred_time="day",
    )
    day_pref_night_score = city_image_autofill._photo_relevance_score(
        photo,
        item=item,
        query=night_query,
        preferred_time="day",
    )

    assert night_pref_night_score > night_pref_day_score
    assert day_pref_day_score > day_pref_night_score
