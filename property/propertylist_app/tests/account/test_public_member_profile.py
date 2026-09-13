import pytest
from django.contrib.auth import get_user_model

from propertylist_app.models import UserProfile

pytestmark = pytest.mark.django_db

User = get_user_model()


def test_member_profile_endpoint_returns_clicked_users_safe_profile(api_client):
    viewer = User.objects.create_user(
        username="profile_viewer",
        email="profile_viewer@example.com",
        password="StrongPass1!",
    )
    target = User.objects.create_user(
        username="profile_target",
        email="private-target@example.com",
        password="StrongPass1!",
        first_name="Abioye",
        last_name="Oyatoye",
    )

    profile, _ = UserProfile.objects.get_or_create(user=target)
    profile.role = "seeker"
    profile.occupation = "Engineer"
    profile.postcode = "SO31 2BX"
    profile.address_manual = "10 Private Street, Southampton"
    profile.date_of_birth = "1990-01-01"
    profile.about_you = "Friendly, tidy and respectful."
    profile.phone = "+447700900123"
    profile.save()

    api_client.force_authenticate(user=viewer)
    response = api_client.get(
        f"/api/v1/users/{target.id}/profile-page/?role=landlord",
        format="json",
    )

    assert response.status_code == 200, getattr(response, "data", None)

    data = response.json()["data"]

    assert data["id"] == target.id
    assert data["display_name"] == "Abioye Oyatoye"
    assert data["username"] == "profile_target"
    assert data["role"] == "landlord"
    assert data["occupation"] == "Engineer"
    assert data["about_you"] == "Friendly, tidy and respectful."
    assert data["location"] == "SO31 area"
    assert "date_joined" in data
    assert "avatar" in data
    assert "total_reviews" in data
    assert "overall_rating" in data
    assert "reviews_preview" in data

    # A member profile may be viewed by another signed-in RentCrib user, but
    # account/contact/private-address data must never be exposed by this route.
    for private_field in (
        "email",
        "phone",
        "postcode",
        "address_manual",
        "date_of_birth",
    ):
        assert private_field not in data
