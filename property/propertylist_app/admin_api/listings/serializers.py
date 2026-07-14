from rest_framework import serializers


class ListingMetricsSerializer(serializers.Serializer):
    total_listing = serializers.IntegerField()
    active_listing = serializers.IntegerField()
    pending_listing = serializers.IntegerField()
    hidden_listing = serializers.IntegerField()
    drafts_listing = serializers.IntegerField()
    unpublished_listing = serializers.IntegerField()
    expired_listing = serializers.IntegerField()
    edited_listing = serializers.IntegerField()
    deleted_listing = serializers.IntegerField()


class AdminListingItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    owner = serializers.CharField()
    owner_email = serializers.EmailField()
    category = serializers.CharField(allow_null=True)
    price = serializers.CharField()
    status = serializers.CharField()
    is_deleted = serializers.BooleanField()
    furnished = serializers.BooleanField()
    bills_included = serializers.BooleanField()
    parking_available = serializers.BooleanField()
    is_available = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class ListingPaginationSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    total_results = serializers.IntegerField()
    has_next = serializers.BooleanField()
    has_previous = serializers.BooleanField()


class ListingOverviewDataSerializer(serializers.Serializer):
    metrics = ListingMetricsSerializer()
    results = AdminListingItemSerializer(many=True)
    pagination = ListingPaginationSerializer()


class ListingOverviewResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = ListingOverviewDataSerializer()


class ListingActionRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=[
            ("approve", "Approve"),
            ("hide", "Hide"),
            ("restore", "Restore"),
            ("publish", "Publish"),
            ("soft_delete", "Soft delete"),
        ]
    )


class ListingActionDataSerializer(serializers.Serializer):
    message = serializers.CharField()
    listing = AdminListingItemSerializer()
    updated_at = serializers.DateTimeField()


class ListingActionResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = ListingActionDataSerializer()
    
    
    
class AdminListingImageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    url = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    uploaded_at = serializers.DateTimeField()


class AdminListingCoreInformationSerializer(serializers.Serializer):
    ad_title = serializers.CharField()
    owner = serializers.CharField()
    owner_email = serializers.EmailField()
    property_type = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    price = serializers.CharField()
    description = serializers.CharField()
    main_photo = serializers.CharField(allow_null=True, required=False)
    images = AdminListingImageSerializer(many=True)


class AdminListingBasicDetailsSerializer(serializers.Serializer):
    address = serializers.CharField()
    deposit = serializers.CharField(allow_null=True)
    view_available_days = serializers.CharField()
    available_from = serializers.DateField()
    availability_start_time = serializers.TimeField(allow_null=True)
    availability_end_time = serializers.TimeField(allow_null=True)
    minimum_rental_period_months = serializers.IntegerField(allow_null=True)
    maximum_rental_period_months = serializers.IntegerField(allow_null=True)
    furnished = serializers.BooleanField()
    bills_included = serializers.BooleanField()
    parking_available = serializers.BooleanField()
    is_available = serializers.BooleanField()


class AdminListingAmenitiesSerializer(serializers.Serializer):
    home = serializers.ListField(child=serializers.CharField())
    property = serializers.ListField(child=serializers.CharField())
    safety = serializers.ListField(child=serializers.CharField())


class AdminListingLayoutInformationSerializer(serializers.Serializer):
    bedrooms = serializers.IntegerField(allow_null=True)
    bathrooms = serializers.IntegerField(allow_null=True)
    property_type = serializers.CharField(allow_null=True)
    room_size = serializers.CharField(allow_null=True)
    shared_living = serializers.BooleanField()
    amenities = AdminListingAmenitiesSerializer()


class AdminExistingFlatmateSerializer(serializers.Serializer):
    age = serializers.IntegerField(allow_null=True)
    nationality = serializers.CharField(allow_blank=True)
    language = serializers.CharField(allow_blank=True)
    gender = serializers.CharField(allow_blank=True)
    occupation = serializers.CharField(allow_blank=True)
    smoking = serializers.CharField(allow_blank=True)
    pets = serializers.CharField(allow_blank=True)
    lgbtqia_household = serializers.CharField(allow_blank=True)
    
    
    
    


class AdminFlatmatePreferencesSerializer(serializers.Serializer):
    nationality = serializers.CharField(allow_blank=True)
    language = serializers.CharField(allow_blank=True)
    min_age = serializers.IntegerField(allow_null=True)
    max_age = serializers.IntegerField(allow_null=True)
    occupation = serializers.CharField(allow_blank=True)
    pets = serializers.CharField(allow_blank=True)
    gender = serializers.CharField(allow_blank=True)
    smoking = serializers.CharField(allow_blank=True)
    partners_allowed = serializers.CharField(allow_blank=True)
    lgbtqia = serializers.CharField(allow_blank=True)
    vegan_vegetarian = serializers.CharField(allow_blank=True)


class AdminListingFlatmateInformationSerializer(serializers.Serializer):
    existing_flatmate = AdminExistingFlatmateSerializer()
    flatmate_preferences = AdminFlatmatePreferencesSerializer()



class AdminListingMetadataSerializer(serializers.Serializer):
    paid_until = serializers.DateTimeField(allow_null=True)
    last_updated = serializers.DateTimeField()
    views_count = serializers.IntegerField()
    inquiries_count = serializers.IntegerField()
    created_at = serializers.DateTimeField()


class AdminRelatedBookingSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class AdminPaymentHistorySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    amount = serializers.CharField()
    currency = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class AdminOwnerProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.EmailField()


class AdminRelatedEntitiesSerializer(serializers.Serializer):
    owner_profile = AdminOwnerProfileSerializer()
    related_bookings = AdminRelatedBookingSerializer(many=True)
    payment_history = AdminPaymentHistorySerializer(many=True)


class AdminAvailableActionsSerializer(serializers.Serializer):
    can_approve = serializers.BooleanField()
    can_hide = serializers.BooleanField()
    can_restore = serializers.BooleanField()
    can_soft_delete = serializers.BooleanField()






class AdminListingDetailDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    listing_id = serializers.CharField()
    status = serializers.CharField()
    basic_information = serializers.DictField()
    core_listing_information = AdminListingCoreInformationSerializer()
    basic_details = AdminListingBasicDetailsSerializer()
    layout_information = AdminListingLayoutInformationSerializer()
    flatmate_information = AdminListingFlatmateInformationSerializer()
    metadata = AdminListingMetadataSerializer()
    related_entities = AdminRelatedEntitiesSerializer()
    available_actions = AdminAvailableActionsSerializer()


class AdminListingDetailResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    message = serializers.CharField()
    data = AdminListingDetailDataSerializer()    