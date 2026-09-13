import hashlib
import json
from io import BytesIO

from propertylist_app.services.city_image_reconciliation import (
    reconcile_duplicate_city_images,
)


class FakeStorage:
    def __init__(self):
        self.files = {}

    def exists(self, name):
        return name in self.files

    def open(self, name, mode="rb"):
        return BytesIO(self.files[name])

    def save(self, name, content):
        content.seek(0)
        self.files[name] = content.read()
        return name

    def delete(self, name):
        self.files.pop(name, None)


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


def test_reconciliation_replaces_only_duplicate_extras_and_biases_them_to_night():
    storage = FakeStorage()
    keeper = FakeCity(
        pk=1,
        name="Birmingham",
        slug="birmingham",
        storage=storage,
        image_name="city_images/birmingham.jpg",
    )
    duplicate_by_hash = FakeCity(
        pk=2,
        name="Leeds",
        slug="leeds",
        storage=storage,
        image_name="city_images/leeds.jpg",
    )
    unique = FakeCity(
        pk=3,
        name="London",
        slug="london",
        storage=storage,
        image_name="city_images/london.jpg",
    )
    duplicate_by_photo_id = FakeCity(
        pk=4,
        name="Sheffield",
        slug="sheffield",
        storage=storage,
        image_name="city_images/sheffield.jpg",
    )

    _write_city(
        storage,
        keeper,
        image_bytes=b"same-image-content",
        photo_id="111",
        search_query="Birmingham England United Kingdom city skyline",
    )
    _write_city(
        storage,
        duplicate_by_hash,
        image_bytes=b"same-image-content",
        photo_id="222",
        search_query="Leeds England United Kingdom city skyline",
    )
    _write_city(
        storage,
        unique,
        image_bytes=b"unique-london-content",
        photo_id="333",
        search_query="London England United Kingdom landmark",
    )
    _write_city(
        storage,
        duplicate_by_photo_id,
        image_bytes=b"different-file-but-same-pexels-photo",
        photo_id="111",
        search_query="Sheffield England United Kingdom city centre",
    )

    calls = []

    def fake_replace(city_id, *, preferred_time, **kwargs):
        calls.append(
            (
                city_id,
                preferred_time,
                set(kwargs["used_photo_ids"]),
                set(kwargs["used_hashes"]),
            )
        )
        query = (
            "replacement city skyline at night"
            if preferred_time == "night"
            else "replacement city skyline"
        )
        return {
            "status": "imported",
            "city_id": city_id,
            "provider_photo_id": f"new-{city_id}",
            "content_sha256": f"newhash-{city_id}",
            "search_query": query,
        }

    result = reconcile_duplicate_city_images(
        cities=[keeper, duplicate_by_hash, unique, duplicate_by_photo_id],
        city_model=FakeCityModel,
        catalogue=_catalogue(
            keeper,
            duplicate_by_hash,
            unique,
            duplicate_by_photo_id,
        ),
        replace_image=fake_replace,
    )

    initial_hashes = {
        hashlib.sha256(b"same-image-content").hexdigest(),
        hashlib.sha256(b"unique-london-content").hexdigest(),
        hashlib.sha256(b"different-file-but-same-pexels-photo").hexdigest(),
    }

    assert result["status"] == "ok"
    assert result["duplicate_city_ids"] == [2, 4]
    assert [(call[0], call[1]) for call in calls] == [(2, "night"), (4, "night")]
    assert calls[0][2] == {"111", "222", "333"}
    assert calls[0][3] == initial_hashes
    assert calls[1][2] == {"111", "222", "333", "new-2"}
    assert calls[1][3] == initial_hashes | {"newhash-2"}
    assert [item["city_id"] for item in result["replaced"]] == [2, 4]
    assert result["failed"] == []
    assert result["night_count"] == 2
    assert result["day_count"] == 2
    assert keeper.image.name == "city_images/birmingham.jpg"
    assert unique.image.name == "city_images/london.jpg"
    assert keeper.image_is_approved is True
    assert unique.image_is_approved is True


def test_reconciliation_failure_does_not_unapprove_or_clear_existing_city_image():
    storage = FakeStorage()
    keeper = FakeCity(
        pk=1,
        name="Birmingham",
        slug="birmingham",
        storage=storage,
        image_name="city_images/birmingham.jpg",
    )
    duplicate = FakeCity(
        pk=2,
        name="Leeds",
        slug="leeds",
        storage=storage,
        image_name="city_images/leeds.jpg",
    )

    _write_city(
        storage,
        keeper,
        image_bytes=b"duplicate-content",
        photo_id="111",
        search_query="Birmingham England United Kingdom city skyline",
    )
    _write_city(
        storage,
        duplicate,
        image_bytes=b"duplicate-content",
        photo_id="222",
        search_query="Leeds England United Kingdom city skyline",
    )

    def failing_replace(city_id, *, preferred_time, **kwargs):
        return {
            "status": "failed",
            "city_id": city_id,
            "error": "simulated Pexels failure",
        }

    original_name = duplicate.image.name
    result = reconcile_duplicate_city_images(
        cities=[keeper, duplicate],
        city_model=FakeCityModel,
        catalogue=_catalogue(keeper, duplicate),
        replace_image=failing_replace,
    )

    assert result["status"] == "partial"
    assert result["duplicate_city_ids"] == [2]
    assert result["replaced"] == []
    assert result["failed"] == [
        {
            "city_id": 2,
            "city": "Leeds",
            "error": "simulated Pexels failure",
        }
    ]
    assert duplicate.image.name == original_name
    assert duplicate.image_is_approved is True
