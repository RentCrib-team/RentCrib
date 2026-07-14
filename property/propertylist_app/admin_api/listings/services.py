from django.core.paginator import Paginator
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from propertylist_app.api.serializers import RoomSerializer
from propertylist_app.models import Room, RoomImage


from propertylist_app.models import (
    Booking,
    MessageThread,
    Payment,
    Room,
    RoomImage,
)



from .selectors import (
    get_admin_listing_metrics,
    get_admin_listings_queryset,
    get_listing_display_status,
)


def _owner_name(user):
    full_name = f"{user.first_name} {user.last_name}".strip()
    return full_name or user.email or user.username


def get_listing_metadata(room):
    inquiries_count = MessageThread.objects.filter(
        participants=room.property_owner
    ).count()

    return {
        "paid_until": room.paid_until,
        "last_updated": room.updated_at,
        "views_count": room.views_count,
        "inquiries_count": inquiries_count,
        "created_at": room.created_at,
    }


def get_related_entities(room):
    bookings = Booking.objects.filter(room=room).order_by("-created_at")[:5]
    payments = Payment.objects.filter(room=room).order_by("-created_at")[:5]

    return {
        "owner_profile": {
            "id": room.property_owner.id,
            "name": _owner_name(room.property_owner),
            "email": room.property_owner.email,
        },
        "related_bookings": [
            {
                "id": booking.id,
                "status": booking.status,
                "start": booking.start,
                "end": booking.end,
            }
            for booking in bookings
        ],
        "payment_history": [
            {
                "id": payment.id,
                "amount": str(payment.amount),
                "currency": payment.currency,
                "status": payment.status,
                "created_at": payment.created_at,
            }
            for payment in payments
        ],
    }


def get_available_actions(room):
    status_value = get_listing_display_status(room)

    return {
        "can_approve": status_value == "pending",
        "can_hide": status_value == "active",
        "can_restore": status_value == "hidden",
        "can_soft_delete": status_value != "deleted",
    }






def _serialize_listing(room):
    return {
        "id": room.id,
        "title": room.title,
        "owner": _owner_name(room.property_owner),
        "owner_email": room.property_owner.email,
        "category": room.category.name if room.category else None,
        "price": str(room.price_per_month),
        "status": get_listing_display_status(room),
        "is_deleted": room.is_deleted,
        "furnished": room.furnished,
        "bills_included": room.bills_included,
        "parking_available": room.parking_available,
        "is_available": room.is_available,
        "created_at": room.created_at,
        "updated_at": room.updated_at,
    }


def get_listing_overview_data(params):
    page = int(params.get("page", 1))
    page_size = int(params.get("page_size", 12))

    qs = get_admin_listings_queryset(params)

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    return {
        "metrics": get_admin_listing_metrics(),
        "results": [_serialize_listing(room) for room in page_obj.object_list],
        "pagination": {
            "page": page_obj.number,
            "page_size": page_size,
            "total_pages": paginator.num_pages,
            "total_results": paginator.count,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
        },
    }


def update_listing_action(room_id, action):
    try:
        room = Room.objects.get(id=room_id)
    except Room.DoesNotExist:
        raise ValidationError("Listing not found.")

    if action == "approve":
        room.status = "active"
        room.is_deleted = False
        room.deleted_at = None
        room.save(update_fields=["status", "is_deleted", "deleted_at"])
        message = "Listing approved successfully."

    elif action == "hide":
        room.status = "hidden"
        room.save(update_fields=["status"])
        message = "Listing hidden successfully."

    elif action == "restore":
        room.restore()
        message = "Listing restored successfully."

    elif action == "publish":
        room.status = "active"
        room.is_deleted = False
        room.deleted_at = None
        room.save(update_fields=["status", "is_deleted", "deleted_at"])
        message = "Listing published successfully."

    elif action == "soft_delete":
        room.soft_delete()
        message = "Listing soft deleted successfully."

    else:
        raise ValidationError("Invalid listing action.")

    room.refresh_from_db()

    return {
        "message": message,
        "listing": _serialize_listing(room),
        "updated_at": timezone.now(),
    }
    
    
    
def get_listing_detail_data(room_id, request=None):
    try:
        room = (
            Room.objects
            .select_related("property_owner", "category")
            .prefetch_related("roomimage_set")
            .get(id=room_id)
        )
    except Room.DoesNotExist:
        raise ValidationError("Listing not found.")

    room_data = RoomSerializer(room, context={"request": request}).data

    images = []
    for image in room.roomimage_set.all().order_by("id"):
        image_url = None
        if image.image:
            image_url = image.image.url
            if request is not None:
                image_url = request.build_absolute_uri(image_url)

        images.append(
            {
                "id": image.id,
                "url": image_url,
                "status": image.status,
                "uploaded_at": image.uploaded_at,
            }
        )

    return {
        "id": room.id,
        "listing_id": f"LT{room.id:04d}",
        "status": get_listing_display_status(room),
        "basic_information": room_data,
        "core_listing_information": {
            "ad_title": room.title,
            "owner": _owner_name(room.property_owner),
            "owner_email": room.property_owner.email,
            "property_type": room.property_type,
            "category": room.category.name if room.category else None,
            "price": str(room.price_per_month),
            "description": room.description,
            "main_photo": room_data.get("main_photo"),
            "images": images,
        },
        "basic_details": {
            "address": room.location,
            "deposit": str(room.security_deposit) if room.security_deposit is not None else None,
            "view_available_days": room.view_available_days_mode,
            "available_from": room.available_from,
            "availability_start_time": room.availability_from_time,
            "availability_end_time": room.availability_to_time,
            "minimum_rental_period_months": room.min_stay_months,
            "maximum_rental_period_months": room.max_stay_months,
            "furnished": room.furnished,
            "bills_included": room.bills_included,
            "parking_available": room.parking_available,
            "is_available": room.is_available,
        },
        
            "layout_information": {
                "bedrooms": room.number_of_bedrooms,
                "bathrooms": room.number_of_bathrooms,
                "property_type": room.property_type,
                "room_size": room.room_size,
                "shared_living": room.is_shared_living,
                "amenities": {
                    "home": [
                        item for item in (room.amenities or [])
                        if item in {
                            "in_unit_laundry",
                            "broadband_inclusive",
                            "en_suite",
                            "bills_inclusive",
                            "tv",
                            "air_conditioning",
                            "furnished",
                            "unfurnished",
                            "balcony",
                            "pets_allowed",
                            "large_closet",
                            "private_bath",
                        }
                ],
                    
            "flatmate_information": {
                "existing_flatmate": {
                    "age": room.existing_flatmate_age,
                    "nationality": room.existing_flatmate_nationality,
                    "language": room.existing_flatmate_language,
                    "gender": room.existing_flatmate_gender,
                    "occupation": room.existing_flatmate_occupation,
                    "smoking": room.existing_flatmate_smoking,
                    "pets": room.existing_flatmate_pets,
                    "lgbtqia_household": room.existing_flatmate_lgbtqia_household,
                    "metadata": get_listing_metadata(room),
                    "related_entities": get_related_entities(room),
                    "available_actions": get_available_actions(room),
                    
                },
                "flatmate_preferences": {
                    "nationality": room.preferred_flatmate_nationality,
                    "language": room.preferred_flatmate_language,
                    "min_age": room.preferred_flatmate_min_age,
                    "max_age": room.preferred_flatmate_max_age,
                    "occupation": room.preferred_flatmate_occupation,
                    "pets": room.preferred_flatmate_pets,
                    "gender": room.preferred_flatmate_gender,
                    "smoking": room.preferred_flatmate_smoking,
                    "partners_allowed": room.preferred_flatmate_partners_allowed,
                    "lgbtqia": room.preferred_flatmate_lgbtqia,
                    "vegan_vegetarian": room.preferred_flatmate_vegan_vegetarian,
                    },
                },        
                    
                "property": [
                    item for item in (room.amenities or [])
                    if item in {
                        "exercise_equipment",
                        "elevator",
                        "doorman",
                        "heating",
                        "paid_parking",
                        "outdoor_space",
                        "swimming_pool",
                        "free_parking",
                        "bbq_grill",
                        "fire_pit",
                        "pool_table",
                    }
                ],
                "safety": [
                    item for item in (room.amenities or [])
                    if item in {
                        "smoke_alarm",
                        "first_aid_kit",
                        "security_system",
                        "carbon_monoxide",
                        "fire_extinguisher",
                        "disabled_accessible",
                        "must_climb_stairs",
                    }
                ],
            },
        },
    }    