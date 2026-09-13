import hashlib
import json
from io import BytesIO

from propertylist_app.services.city_image_mismatch_reconciliation import (
    reconcile_mismatched_city_images,
)


class FakeStorage:
    def __init__(self):
        self.files = {}

    def exists(self, name):
        return name in self.files

    def open(self, name, mode="rb"):
        return BytesIO(self.files[name])


class FakeImage:
    def __init__(self, storage, name):
        self.storage = storage
        self.name = name

    def __bool__(self):
        return bool(self.name)


class FakeCity:
    def __init__(self, *, pk, name, slug, storage, image_name):
        self.pk = pk
        self.name = name
        self.slug = slug
        self.image = FakeImage(storage, image_name)
        self.image_is_approved = True


class FakeCityModel:
    pass


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _write_city(storage, city, *, image_bytes, photo_id, search_query):
    storage.files[city.image.name] = image_bytes
    storage.files[f"city_image_provenance/{city.slug}.json"] = json.dumps(
        {
            "provider": "Pexels",
            "provider_photo_id": photo_id,
            "stored_image": city.image.name,
            "search_query": search_query,
        }
    ).encode("utf-8")


def _catalogue(*cities):
    return tuple(
        {
            "name": city.name,
            "display_name": city.name,
            "slug": city.slug,
            "nation": "England",
        }
        for city in cities
    )


def test_mismatch_reconciliation_keeps_city_matches_and_replaces_only_proven_mismatch():
    storage = FakeStorage()
    london = FakeCity(
        pk=1,
        name="London",
        slug="london",
        storage=storage,
        image_name="city_images/london.jpg",
    )
    southampton = FakeCity(
        pk=2,
        name="Southampton",
        slug="southampton",
        storage=storage,
        image_name="city_images/southampton.jpg",
    )

    _write_city(
        storage,
        london,
        image_bytes=b"london-image",
        photo_id="100",
        search_query="London England United Kingdom city skyline",
    )
    _write_city(
        storage,
        southampton,
        image_bytes=b"wrong-southampton-image",
        photo_id="200",
        search_query="Southampton England United Kingdom city skyline at night",
    )

    def fake_get(url, **kwargs):
        if url.endswith("/100"):
            return FakeResponse(
                {
                    "id": 100,
                    "alt": "London skyline and River Thames",
                    "url": "https://www.pexels.com/photo/london-skyline-100/",
                }
            )
        if url.endswith("/200"):
            return FakeResponse(
                {
                    "id": 200,
                    "alt": "Aerial view of Liverpool city skyline",
                    "url": "https://www.pexels.com/photo/liverpool-skyline-200/",
                }
            )
        raise AssertionError(f"unexpected request: {url}")

    replacement_calls = []

    def fake_replace(city_id, *, preferred_time, **kwargs):
        replacement_calls.append(
            {
                "city_id": city_id,
                "preferred_time": preferred_time,
                "used_photo_ids": set(kwargs["used_photo_ids"]),
                "used_hashes": set(kwargs["used_hashes"]),
            }
        )
        return {
            "status": "imported",
            "city_id": city_id,
            "provider_photo_id": "300",
            "content_sha256": "new-southampton-hash",
        }

    progress = []
    result = reconcile_mismatched_city_images(
        cities=[london, southampton],
        city_model=FakeCityModel,
        catalogue=_catalogue(london, southampton),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
        progress=progress.append,
    )

    expected_hashes = {
        hashlib.sha256(b"london-image").hexdigest(),
        hashlib.sha256(b"wrong-southampton-image").hexdigest(),
    }

    assert result["status"] == "ok"
    assert result["matched"] == [
        {"city_id": 1, "city": "London", "photo_id": "100"}
    ]
    assert result["mismatched_city_ids"] == [2]
    assert [item["city_id"] for item in result["replaced"]] == [2]
    assert result["failed"] == []
    assert result["unknown"] == []
    assert replacement_calls == [
        {
            "city_id": 2,
            "preferred_time": "night",
            "used_photo_ids": {"100", "200"},
            "used_hashes": expected_hashes,
        }
    ]
    assert london.image.name == "city_images/london.jpg"
    assert london.image_is_approved is True
    assert southampton.image_is_approved is True
    assert progress == [
        "Auditing 2 approved city images for city mismatch",
        "[1/2] London: match",
        "[2/2] Southampton: mismatch",
        "Found 1 mismatched city images to replace",
        "[1/1] Southampton: searching Pexels (night)",
        "[1/1] Southampton: replaced",
    ]


def test_mismatch_reconciliation_does_not_clear_existing_image_when_replacement_fails():
    storage = FakeStorage()
    southampton = FakeCity(
        pk=2,
        name="Southampton",
        slug="southampton",
        storage=storage,
        image_name="city_images/southampton.jpg",
    )
    _write_city(
        storage,
        southampton,
        image_bytes=b"wrong-southampton-image",
        photo_id="200",
        search_query="Southampton England United Kingdom city skyline",
    )

    def fake_get(url, **kwargs):
        return FakeResponse(
            {
                "id": 200,
                "alt": "Aerial view of Liverpool city skyline",
                "url": "https://www.pexels.com/photo/liverpool-skyline-200/",
            }
        )

    def failing_replace(city_id, *, preferred_time, **kwargs):
        return {
            "status": "failed",
            "city_id": city_id,
            "error": "no city-matched replacement",
        }

    original_name = southampton.image.name
    result = reconcile_mismatched_city_images(
        cities=[southampton],
        city_model=FakeCityModel,
        catalogue=_catalogue(southampton),
        replace_image=failing_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "partial"
    assert result["mismatched_city_ids"] == [2]
    assert result["replaced"] == []
    assert result["failed"] == [
        {
            "city_id": 2,
            "city": "Southampton",
            "error": "no city-matched replacement",
        }
    ]
    assert southampton.image.name == original_name
    assert southampton.image_is_approved is True
