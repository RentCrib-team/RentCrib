import pytest

from propertylist_app.services.city_image_autofill import (
    PEXELS_SEARCH_URL,
    _find_photo_candidates,
    _photo_matches_city,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _item(name="Southampton", slug="southampton", nation="England"):
    return {
        "name": name,
        "display_name": name,
        "slug": slug,
        "nation": nation,
    }


def _photo(photo_id, *, alt, url):
    return {
        "id": photo_id,
        "alt": alt,
        "url": url,
        "photographer": "Example Photographer",
        "width": 2400,
        "height": 1350,
        "src": {"large2x": f"https://images.example/{photo_id}.jpg"},
    }


def test_pexels_candidates_require_photo_metadata_to_match_city_not_search_query():
    item = _item()
    wrong_city = _photo(
        100,
        alt="Portsmouth waterfront skyline at night",
        url="https://www.pexels.com/photo/portsmouth-waterfront-100/",
    )
    correct_city = _photo(
        200,
        alt="Southampton city skyline and waterfront",
        url="https://www.pexels.com/photo/southampton-city-skyline-200/",
    )
    calls = []

    def fake_get(url, **kwargs):
        assert url == PEXELS_SEARCH_URL
        calls.append(kwargs["params"]["query"])
        return FakeResponse({"photos": [wrong_city, correct_city]})

    candidates = _find_photo_candidates(
        item=item,
        api_key="test-key",
        http_get=fake_get,
        preferred_time="night",
    )

    assert len(calls) == 5
    assert candidates
    assert {candidate[2]["id"] for candidate in candidates} == {200}
    assert _photo_matches_city(correct_city, item=item) is True
    assert _photo_matches_city(wrong_city, item=item) is False


def test_pexels_candidates_fail_closed_when_no_photo_metadata_matches_city():
    item = _item()
    wrong_city = _photo(
        100,
        alt="Portsmouth waterfront skyline",
        url="https://www.pexels.com/photo/portsmouth-waterfront-100/",
    )

    def fake_get(url, **kwargs):
        assert url == PEXELS_SEARCH_URL
        return FakeResponse({"photos": [wrong_city]})

    with pytest.raises(RuntimeError, match="city-matched image"):
        _find_photo_candidates(
            item=item,
            api_key="test-key",
            http_get=fake_get,
            preferred_time="day",
        )


def test_city_match_uses_boundaries_and_disambiguates_bangor_variants():
    bath_item = _item(name="Bath", slug="bath")
    bathroom_photo = _photo(
        300,
        alt="Modern bathroom interior",
        url="https://www.pexels.com/photo/modern-bathroom-300/",
    )
    assert _photo_matches_city(bathroom_photo, item=bath_item) is False

    bangor_wales = _item(name="Bangor", slug="bangor-wales", nation="Wales")
    bangor_ni_photo = _photo(
        400,
        alt="Bangor Northern Ireland harbour",
        url="https://www.pexels.com/photo/bangor-northern-ireland-400/",
    )
    bangor_wales_photo = _photo(
        500,
        alt="Bangor Wales city view",
        url="https://www.pexels.com/photo/bangor-wales-500/",
    )
    assert _photo_matches_city(bangor_ni_photo, item=bangor_wales) is False
    assert _photo_matches_city(bangor_wales_photo, item=bangor_wales) is True
