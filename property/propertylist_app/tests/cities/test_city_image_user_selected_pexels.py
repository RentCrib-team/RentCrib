from propertylist_app.services import city_image_user_selected_pexels as selected
from propertylist_app.services.city_image_autofill import (
    CITY_MATCH_ALIASES,
    PEXELS_SEARCH_URL,
)


EXPECTED_PUBLIC_CITYSCAPE_SLUGS = (
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


class FakeImage:
    def __init__(self, name):
        self.name = name

    def __bool__(self):
        return bool(self.name)


class FakeCity:
    def __init__(self, *, pk, name, slug):
        self.pk = pk
        self.name = name
        self.slug = slug
        self.image = FakeImage(f"city_images/{slug}.jpg")
        self.image_is_approved = True
        self.is_active = True


class FakeQuerySet(list):
    def filter(self, **kwargs):
        result = self
        for key, value in kwargs.items():
            if key in {"is_active", "image_is_approved"}:
                result = FakeQuerySet(
                    [item for item in result if getattr(item, key) == value]
                )
        return result

    def exclude(self, **kwargs):
        result = self
        for key, value in kwargs.items():
            if key == "image":
                result = FakeQuerySet(
                    [item for item in result if item.image.name != value]
                )
            elif key == "image__isnull" and value is True:
                result = FakeQuerySet(
                    [item for item in result if item.image is not None]
                )
        return result

    def order_by(self, *args):
        return self


class FakeManager:
    def __init__(self, cities):
        self._cities = FakeQuerySet(cities)

    def filter(self, **kwargs):
        return self._cities.filter(**kwargs)


class FakeCityModel:
    objects = None


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


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


def test_public_cityscape_source_is_exact_top_twenty_and_pinned_ids_are_unique():
    assert selected.PUBLIC_CITYSCAPE_SLUGS == EXPECTED_PUBLIC_CITYSCAPE_SLUGS
    assert len(selected.PUBLIC_CITYSCAPE_SLUGS) == 20
    assert len(set(selected.PUBLIC_CITYSCAPE_SLUGS)) == 20
    assert set(selected.USER_SELECTED_PEXELS_PHOTO_IDS).issubset(
        set(selected.PUBLIC_CITYSCAPE_SLUGS)
    )
    assert len(set(selected.USER_SELECTED_PEXELS_PHOTO_IDS.values())) == len(
        selected.USER_SELECTED_PEXELS_PHOTO_IDS
    )


def test_cityscape_quality_gate_accepts_whole_city_and_rejects_single_building():
    assert selected._photo_is_broad_cityscape(
        {
            "alt": (
                "Aerial view of Leicester cityscape with rooftops, streets "
                "and a broad urban skyline"
            ),
            "url": "https://www.pexels.com/photo/leicester-cityscape-123/",
        }
    )
    assert not selected._photo_is_broad_cityscape(
        {
            "alt": "A historic red-brick building in Leicester, England",
            "url": "https://www.pexels.com/photo/red-brick-building-leicester-456/",
        }
    )


def test_service_uses_pinned_broad_photos_and_keeps_cross_city_uniqueness(
    monkeypatch,
):
    london = FakeCity(pk=1, name="London", slug="london")
    brighton = FakeCity(pk=2, name="Brighton & Hove", slug="brighton-hove")
    other = FakeCity(pk=3, name="Other", slug="other")
    FakeCityModel.objects = FakeManager([london, brighton, other])

    monkeypatch.setattr(
        selected,
        "_city_image_records",
        lambda cities: [
            {
                "city": london,
                "photo_id": "old-london",
                "content_sha256": "hash-l",
                "is_night": False,
            },
            {
                "city": brighton,
                "photo_id": "old-brighton",
                "content_sha256": "hash-b",
                "is_night": False,
            },
            {
                "city": other,
                "photo_id": "used-other",
                "content_sha256": "hash-o",
                "is_night": False,
            },
        ],
    )

    photos = {
        "16435133": {
            "id": 16435133,
            "alt": "Panoramic aerial view of modern London cityscape and skyline",
            "url": "https://www.pexels.com/photo/cityscape-of-london-england-16435133/",
            "src": {"large": "https://images.pexels.com/london.jpg"},
            "width": 1600,
            "height": 900,
        },
        "37153111": {
            "id": 37153111,
            "alt": (
                "Panoramic Brighton beach and city skyline with buildings "
                "along the seafront"
            ),
            "url": "https://www.pexels.com/photo/brighton-beach-scenic-view-with-i360-37153111/",
            "src": {"large": "https://images.pexels.com/brighton.jpg"},
            "width": 1600,
            "height": 900,
        },
    }

    def fake_get(url, **kwargs):
        photo_id = url.rsplit("/", 1)[-1]
        return FakeResponse(photos[photo_id])

    calls = []

    def fake_replace(city_id, **kwargs):
        injected = kwargs["http_get"](PEXELS_SEARCH_URL).json()["photos"][0]
        calls.append(
            {
                "city_id": city_id,
                "photo_id": str(injected["id"]),
                "used_photo_ids": set(kwargs["used_photo_ids"]),
                "used_hashes": set(kwargs["used_hashes"]),
            }
        )
        return {
            "status": "imported",
            "provider_photo_id": str(injected["id"]),
            "content_sha256": f"new-{city_id}",
        }

    assert "brighton-hove" not in CITY_MATCH_ALIASES

    result = selected.apply_user_selected_pexels_city_images(
        slugs=["london", "brighton-hove"],
        city_model=FakeCityModel,
        catalogue=_catalogue(london, brighton, other),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "ok"
    assert result["failed"] == []
    assert result["skipped"] == []
    assert [item["provider_photo_id"] for item in result["replaced"]] == [
        "16435133",
        "37153111",
    ]
    assert calls[0]["used_photo_ids"] == {"old-brighton", "used-other"}
    assert calls[0]["used_hashes"] == {"hash-b", "hash-o"}
    assert calls[1]["used_photo_ids"] == {"16435133", "used-other"}
    assert calls[1]["used_hashes"] == {"new-1", "hash-o"}
    assert "brighton-hove" not in CITY_MATCH_ALIASES


def test_service_search_fallback_skips_single_building_and_uses_broad_cityscape(
    monkeypatch,
):
    leicester = FakeCity(pk=1, name="Leicester", slug="leicester")
    FakeCityModel.objects = FakeManager([leicester])

    monkeypatch.setattr(
        selected,
        "_city_image_records",
        lambda cities: [
            {
                "city": leicester,
                "photo_id": "old",
                "content_sha256": "old-hash",
                "is_night": False,
            }
        ],
    )

    single_building = {
        "id": 10,
        "alt": "A historic red-brick building in Leicester, England",
        "url": "https://www.pexels.com/photo/leicester-building-10/",
        "src": {"large": "https://images.pexels.com/leicester-building.jpg"},
        "width": 1600,
        "height": 900,
    }
    broad_city = {
        "id": 20,
        "alt": (
            "Aerial view of Leicester cityscape with rooftops, streets "
            "and a wide urban skyline"
        ),
        "url": "https://www.pexels.com/photo/leicester-cityscape-20/",
        "src": {"large": "https://images.pexels.com/leicester-cityscape.jpg"},
        "width": 1600,
        "height": 900,
    }

    def fake_get(url, **kwargs):
        if url == PEXELS_SEARCH_URL:
            return FakeResponse({"photos": [single_building, broad_city]})
        raise AssertionError(url)

    calls = []

    def fake_replace(city_id, **kwargs):
        injected = kwargs["http_get"](PEXELS_SEARCH_URL).json()["photos"][0]
        calls.append(str(injected["id"]))
        return {
            "status": "imported",
            "provider_photo_id": str(injected["id"]),
            "content_sha256": "new-hash",
        }

    result = selected.apply_user_selected_pexels_city_images(
        slugs=["leicester"],
        city_model=FakeCityModel,
        catalogue=_catalogue(leicester),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "ok"
    assert calls == ["20"]
    assert result["replaced"] == [
        {
            "city_id": 1,
            "city": "Leicester",
            "provider_photo_id": "20",
        }
    ]


def test_service_allows_reapplying_same_photo_to_its_own_city(monkeypatch):
    london = FakeCity(pk=1, name="London", slug="london")
    other = FakeCity(pk=2, name="Other", slug="other")
    FakeCityModel.objects = FakeManager([london, other])

    monkeypatch.setattr(
        selected,
        "_city_image_records",
        lambda cities: [
            {
                "city": london,
                "photo_id": "16435133",
                "content_sha256": "hash-l",
                "is_night": False,
            },
            {
                "city": other,
                "photo_id": "used-other",
                "content_sha256": "hash-o",
                "is_night": False,
            },
        ],
    )

    def fake_get(url, **kwargs):
        return FakeResponse(
            {
                "id": 16435133,
                "alt": "Panoramic aerial view of modern London cityscape and skyline",
                "url": "https://www.pexels.com/photo/cityscape-of-london-england-16435133/",
                "src": {"large": "https://images.pexels.com/london.jpg"},
                "width": 1600,
                "height": 900,
            }
        )

    calls = []

    def fake_replace(city_id, **kwargs):
        calls.append(
            {
                "used_photo_ids": set(kwargs["used_photo_ids"]),
                "used_hashes": set(kwargs["used_hashes"]),
            }
        )
        return {
            "status": "imported",
            "provider_photo_id": "16435133",
            "content_sha256": "new-london-hash",
        }

    result = selected.apply_user_selected_pexels_city_images(
        slugs=["london"],
        city_model=FakeCityModel,
        catalogue=_catalogue(london, other),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "ok"
    assert calls == [
        {
            "used_photo_ids": {"used-other"},
            "used_hashes": {"hash-o"},
        }
    ]


def test_service_rejects_wrong_live_metadata_without_replacing(monkeypatch):
    london = FakeCity(pk=1, name="London", slug="london")
    FakeCityModel.objects = FakeManager([london])

    monkeypatch.setattr(
        selected,
        "_city_image_records",
        lambda cities: [
            {
                "city": london,
                "photo_id": "old",
                "content_sha256": "hash",
                "is_night": False,
            }
        ],
    )

    def fake_get(url, **kwargs):
        return FakeResponse(
            {
                "id": 16435133,
                "alt": "Panoramic aerial view of Manchester cityscape and skyline",
                "url": "https://www.pexels.com/photo/manchester-cityscape-16435133/",
                "src": {"large": "https://images.pexels.com/manchester.jpg"},
                "width": 1600,
                "height": 900,
            }
        )

    called = False

    def fake_replace(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "imported"}

    result = selected.apply_user_selected_pexels_city_images(
        slugs=["london"],
        city_model=FakeCityModel,
        catalogue=_catalogue(london),
        replace_image=fake_replace,
        http_get=fake_get,
        api_key="test-key",
    )

    assert result["status"] == "partial"
    assert result["replaced"] == []
    assert called is False
    assert result["failed"] == [
        {
            "city_id": 1,
            "city": "London",
            "error": "Selected Pexels photo metadata does not match the target city",
        }
    ]
