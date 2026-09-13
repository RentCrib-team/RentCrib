Warning: truncated output (original token count: 16092)
Total output lines: 2016

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F, CheckConstraint
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.auth.hashers import check_password, make_password


User = get_user_model()


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def alive(self):
        return self.get_queryset().alive()

    def dead(self):
        return self.get_queryset().dead()



# ---------------------------
# Soft-delete base + queryset
# ---------------------------
class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        qs = self.filter(is_deleted=False)
        # If model has a 'status' field, also require 'active'
        try:
            field_names = {f.name for f in self.model._meta.fields}
            if "status" in field_names:
                qs = qs.exclude(status=Room.Lifecycle.HIDDEN)
        except Exception:
            pass
        return qs

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


# -------------
# RoomCategorie
# -------------
class RoomCategorie(models.Model):
    key = models.CharField(max_length=30, unique=True, blank=True, default="")
    name = models.CharField(max_length=30)
    about = models.TextField(max_length=150, blank=True, default="")
    website = models.URLField(max_length=100, blank=True, default="")
    slug = models.SlugField(max_length=40, unique=True, null=True, blank=True, db_index=True)
    active = models.BooleanField(default=True, db_index=True)

    def save(self, *args, **kwargs):
        # key: required unique; derive from name if empty
        if not (self.key or "").strip():
            base = slugify(self.name) or "category"
            candidate = base[:30]  # enforce max_length
            i = 2
            while RoomCategorie.objects.filter(key=candidate).exclude(pk=self.pk).exists():
                suffix = f"-{i}"
                candidate = base[: (30 - len(suffix))] + suffix
                i += 1
            self.key = candidate

        # slug: keep it unique as well
        if not self.slug:
            base = slugify(self.name) or slugify(self.key)
            candidate = base
            i = 2
            while RoomCategorie.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.slug = candidate

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ----
# City
# ----
class City(models.Model):
    """Canonical city used for city cards and city-based room discovery."""

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True, db_index=True)
    image = models.ImageField(upload_to="city_images/", null=True, blank=True)
    image_is_approved = models.BooleanField(default=False)
    image_alt = models.CharField(max_length=160, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="uq_city_name_lower",
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValidationError({"name": "City name is required."})

        base = slugify(self.slug or self.name) or "city"
        candidate = base[:120]
        i = 2
        while City.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            suffix = f"-{i}"
            candidate = base[: (120 - len(suffix))] + suffix
            i += 1
        self.slug = candidate

        if not (self.image_alt or "").strip():
            self.image_alt = self.name

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ----
# Room
# ----
class Room(SoftDeleteModel):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    price_per_month = models.DecimalField(max_digits=8, decimal_places=2)
    security_deposit = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Security deposit in GBP.",
    )
    location = models.CharField(max_length=255)
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        related_name="rooms",
        null=True,
        blank=True,
        help_text="Canonical city used for city browsing and city cards.",
    )
    category = models.ForeignKey(
        RoomCategorie,
        on_delete=models.CASCADE,
        related_name="room_info",
    )
    available_from = models.DateField(
        default=date.today,
        help_text="Date from which the room will be available for listing / move-in.",
    )
    is_available = models.BooleanField(default=True)
    relisted_at = models.DateTimeField(null=True, default=None)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    furnished = models.BooleanField(default=False)
    bills_included = models.BooleanField(default=False)
    property_owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="rooms",
    )
    image = models.ImageField(upload_to="room_images/", null=True, blank=True)
    number_of_bedrooms = models.IntegerField(default=1)
    number_of_bathrooms = models.IntegerField(default=1)
        # ---- Advanced Search II (Option A) - explicit UI-matching fields ----

    YES_NO_PREF_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("no_preference", "No preference"),
    ]

    BATHROOM_TYPE_CHOICES = [
        ("private", "Private"),
        ("shared", "Shared"),
        ("no_preference", "No preference"),
    ]

    SUITABLE_FOR_CHOICES = [
        ("one_person", "One person"),
        ("couple", "Couple"),
        ("max_occupants", "Maximum occupants"),
        ("no_preference", "No preference"),
    ]

    HOUSEHOLD_TYPE_CHOICES = [
        ("professional", "Professional"),
        ("student", "Student"),
        ("mixed", "Mixed"),
        ("no_preference", "No preference"),
    ]

    HOUSEHOLD_ENVIRONMENT_CHOICES = [
        ("quiet", "Quiet"),
        ("sociable", "Sociable"),
        ("mixed", "Mixed"),
        ("no_preference", "No preference"),
    ]

    bathroom_type = models.CharField(
        max_length=32,
        choices=BATHROOM_TYPE_CHOICES,
        default="no_preference",
        blank=True,
    )

    shared_living_space = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    smoking_allowed_in_property = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    suitable_for = models.CharField(
        max_length=32,
        choices=SUITABLE_FOR_CHOICES,
        default="no_preference",
        blank=True,
    )

    max_occupants = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )

    household_bedrooms_min = models.PositiveSmallIntegerField(null=True, blank=True)
    household_bedrooms_max = models.PositiveSmallIntegerField(null=True, blank=True)

    household_type = models.CharField(
        max_length=32,
        choices=HOUSEHOLD_TYPE_CHOICES,
        default="no_preference",
        blank=True,
    )

    household_environment = models.CharField(
        max_length=32,
        choices=HOUSEHOLD_ENVIRONMENT_CHOICES,
        default="no_preference",
        blank=True,
    )

    pets_allowed = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    inclusive_household = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    accessible_entry = models.CharField(
        max_length=32,
        choices=YES_NO_PREF_CHOICES,
        default="no_preference",
        blank=True,
    )

    free_to_contact = models.BooleanField(default=False)

    property_type = models.CharField(
        max_length=100,
        choices=[
            ("flat", "Flat"),
            ("house", "House"),
            ("studio", "Studio"),
        ],
    )
    parking_available = models.BooleanField(default=False)
    avg_rating = models.FloatField(default=0)
    number_rating = models.IntegerField(default=0)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    paid_until = models.DateField(null=True, blank=True)

    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("active", "Active"),
        ("hidden", "Hidden"),
    )
    class Lifecycle:
        DRAFT = "draft"
        ACTIVE = "active"
        HIDDEN = "hidden"

        ALL = {DRAFT, ACTIVE, HIDDEN}

        PUBLIC = {ACTIVE}
        EDITABLE = {DRAFT, ACTIVE}
    
    
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default="active",
    )

    is_shared_room = models.BooleanField(
        default=False,
        help_text="Room is in an existing flat/house share.",
    )

    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)

    min_stay_months = models.PositiveSmallIntegerField(null=True, blank=True)
    max_stay_months = models.PositiveSmallIntegerField(null=True, blank=True)

    ROOM_FOR_CHOICES = [
        ("any", "Don't mind"),
        ("females", "Females"),
        ("males", "Males"),
        ("couples", "Couples"),
    ]
    room_for = models.CharField(
        max_length=16,
        choices=ROOM_FOR_CHOICES,
        default="any",
    )

    ROOM_SIZE_CHOICES = [
        ("dont_mind", "Don't mind"),
        ("single", "Single"),
        ("double", "Double"),
    ]
    room_size = models.CharField(
        max_length=16,
        choices=ROOM_SIZE_CHOICES,
        default="dont_mind",
    )

    existing_flatmate_age = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Approximate age of current flatmate or average age in the household.",
    )

    EXISTING_GENDER_CHOICES = [
        ("male", "Male"),
        ("female", "Female"),
        ("non_binary", "Non-binary"),
        ("prefer_not_to_say", "Prefer not to say"),
    ]
    existing_flatmate_gender = models.CharField(
        max_length=32,
        choices=EXISTING_GENDER_CHOICES,
        blank=True,
        default="",
    )

    EXISTING_OCCUPATION_CHOICES = [
        ("professional", "Professional"),
        ("student", "Student"),
        ("prefer_not_to_say", "Prefer not to say"),
    ]
    existing_flatmate_occupation = models.CharField(
        max_length=32,
        choices=EXISTING_OCCUPATION_CHOICES,
        blank=True,
        default="",
    )

    existing_flatmate_nationality = models.CharField(max_length=100, blank=True, default="")
    existing_flatmate_language = models.CharField(max_length=100, blank=True, default="")

    YES_NO_PREF_CHOICES = [
        ("yes", "Yes"),
        ("no", "No"),
        ("no_preference", "No preference"),
    ]
    existing_flatmate_smoking = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Do existing flatmates smoke?",
    )
    existing_flatmate_pets = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="",
        help_text="Are there pets in the home?",
    )
    existing_flatmate_lgbtqia_household = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="",
        help_text="Whether the household includes LGBTQIA+ people.",
    )

    preferred_flatmate_nationality = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Preferred nationality of future flatmate (free text from dropdown).",
    )
    preferred_flatmate_language = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Preferred language of future flatmate (free text from dropdown).",
    )

    preferred_flatmate_min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    preferred_flatmate_max_age = models.PositiveSmallIntegerField(null=True, blank=True)

    PREFERRED_OCCUPATION_CHOICES = [
        ("students_only", "For students only"),
        ("not_for_students", "Not for students"),
        ("open_to_everyone", "Open to everyone"),
    ]
    preferred_flatmate_occupation = models.CharField(
        max_length=32,
        choices=PREFERRED_OCCUPATION_CHOICES,
        blank=True,
        default="",
        help_text="Student / non-student preference for future flatmate.",
    )

    preferred_flatmate_pets = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Whether future flatmate can have / be around pets.",
    )
    preferred_flatmate_gender = models.CharField(
        max_length=20,
        choices=[
            ("no_preference", "No preference"),
            ("male", "Male"),
            ("female", "Female"),
            ("others", "Others"),
        ],
        blank=True,
        default="no_preference",
        help_text="Preferred gender of future flatmate.",
    )
    preferred_flatmate_smoking = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Whether future flatmate can smoke or not.",
    )
    preferred_flatmate_partners_allowed = models.CharField(
        max_length=20,
        choices=[
            ("yes", "Yes"),
            ("no", "No"),
        ],
        blank=True,
        default="no",
        help_text="Whether partners are allowed to stay over.",
    )
    preferred_flatmate_lgbtqia = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Preference about LGBTQIA+ flatmates.",
    )
    preferred_flatmate_vegan_vegetarian = models.CharField(
        max_length=20,
        choices=YES_NO_PREF_CHOICES,
        blank=True,
        default="no_preference",
        help_text="Preference about vegan/vegetarian flatmates.",
    )

    availability_from_time = models.TimeField(null=True, blank=True)
    availability_to_time = models.TimeField(null=True, blank=True)

    #  search engine indexing override per listing:
    # None = follow user's default, True = force allow, False = force noindex
    allow_search_indexing_override = models.BooleanField(null=True, blank=True, default=None)


    VIEW_DAYS_CHOICES = [
        ("everyday", "Everyday"),
        ("weekdays", "Weekdays only"),
        ("weekends", "Weekends only"),
        ("custom", "Custom dates"),
    ]
    view_available_days_mode = models.CharField(
        max_length=20,
        choices=VIEW_DAYS_CHOICES,
        default="everyday",
        help_text="Everyday / weekdays only / weekends only / custom dates.",
    )
    view_available_custom_dates = models.JSONField(
        blank=True,
        default=list,
        help_text="List of specific viewing dates when mode is 'custom'.",
    )
    
    cover_photo = models.ForeignKey(
            "RoomImage",
            null=True,
            blank=True,
            on_delete=models.SET_NULL,
            related_name="cover_for_rooms",
            help_text="User-selected cover photo for this room.",
        )
    

    @property
    def is_live(self):
        if self.status != "active" or getattr(self, "is_deleted", False):
            return False
        today = date.today()
        if self.paid_until and self.paid_until < today:
            return False
        return True

    @property
    def is_expired_listing(self):
        if not self.paid_until:
            return False
        return self.paid_until < date.today()

    def clean(self):
        super().clean()

        if (
            self.bills_included
            and self.price_per_month is not None
            and float(self.price_per_month) < 100.0
        ):
            raise ValidationError({"bills_included": "Bills cannot be included for such a low price."})

        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            raise ValidationError({"min_age": "min_age cannot be greater than max_age."})

        if (
            self.min_stay_months is not None
            and self.max_stay_months is not None
            and self.min_stay_months > self.max_stay_months
        ):
            raise ValidationError(
                {"min_stay_months": "min_stay_months cannot be greater than max_stay_months."}
            )

        if (
            self.preferred_flatmate_min_age is not None
            and self.preferred_flatmate_max_age is not None
            and self.preferred_flatmate_min_age > self.preferred_flatmate_max_age
        ):
            raise ValidationError(
                {
                    "preferred_flatmate_min_age": (
                        "preferred_flatmate_min_age cannot be greater than preferred_flatmate_max_age."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.property_owner_id is None:
            raise ValidationError({"property_owner": "property_owner is required."})

        if self.category_id is None:
            raise ValidationError({"category": "category is required."})

        super().save(*args, **kwargs)

    class Meta:
        constraints = [
     …6092 tokens truncated…     "respectful_fair",
                }
                negatives = {
                    "unresponsive",
                    "maintenance_poor",
                    "misleading_listing",
                    "unfair_treatment",
                }
            else:  # landlord -> tenant
                positives = {
                    "clean_and_tidy",
                    "friendly",
                    "good_communication",
                    "paid_on_time",
                    "property_care_good",
                    "followed_rules",
                }
                negatives = {
                    "messy",
                    "rude",
                    "poor_communication",
                    "late_payment",
                    "property_care_poor",
                    "broke_rules",
                }

            pos = sum(1 for f in flags if f in positives)
            neg = sum(1 for f in flags if f in negatives)
            score = 3 + (pos - neg)
            self.overall_rating = max(1, min(5, score))



        super().save(*args, **kwargs)

# ---------------
# WebhookReceipt
# ---------------
# WebhookReceipt is the canonical store for webhook idempotency.
# We use unique event_id values here to prevent duplicate processing
# of the same provider webhook event, including Stripe retries.

class WebhookReceipt(models.Model):
    source = models.CharField(max_length=50, db_index=True)
    event_id = models.CharField(max_length=255, unique=True)
    received_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(null=True, blank=True)
    headers = models.JSONField(null=True, blank=True)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)


# ---------
# SavedRoom
# ---------
class SavedRoom(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_rooms_links")
    room = models.ForeignKey("Room", on_delete=models.CASCADE, related_name="saved_by_links")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "room")
        indexes = [
            models.Index(fields=["user", "room"]),
            models.Index(fields=["room"]),
        ]

    def __str__(self):
        return f"{getattr(self.user, 'username', 'user')} â†’ {getattr(self, 'room_id', 'âˆ…')}"


# -------------
# MessageThread
# -------------
class MessageThread(SoftDeleteModel):
    room = models.ForeignKey(
        "Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="message_threads",
    )
    participants = models.ManyToManyField(User, related_name="message_threads")
    landlord = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="landlord_message_threads",
        help_text="Landlord-side participant snapshotted for role-scoped messaging.",
    )
    seeker = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="seeker_message_threads",
        help_text="Seeker-side participant snapshotted for role-scoped messaging.",
    )
    
    def set_role_participants(self, *, landlord=None, seeker=None):
        """
        Snapshot the business-role relationship for this thread.

        This does not change thread participants and does not infer roles from
        the users' currently selected profile roles.
        """
        update_fields = []

        if landlord is not None and self.landlord_id != landlord.pk:
            self.landlord = landlord
            update_fields.append("landlord")

        if seeker is not None and self.seeker_id != seeker.pk:
            self.seeker = seeker
            update_fields.append("seeker")

        if update_fields:
            self.save(update_fields=update_fields)

        return self
    
    
    created_at = models.DateTimeField(auto_now_add=True)

    label = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        help_text="Optional label for this thread (e.g. 'Viewing scheduled', 'Good fit').",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["room", "landlord", "seeker"],
                condition=models.Q(
                    is_deleted=False,
                    room__isnull=False,
                    landlord__isnull=False,
                    seeker__isnull=False,
                ),
                name="uniq_active_thread_room_landlord_seeker",
            ),
        ]

    def __str__(self):
        users = ", ".join(self.participants.values_list("username", flat=True)[:2])
        return f"Thread {self.id} ({users}â€¦)"


class MessageThreadState(models.Model):
    LABEL_CHOICES = [
        ("viewing_scheduled", "Viewing scheduled"),
        ("viewing_done", "Viewing done"),
        ("good_fit", "Good fit"),
        ("unsure", "Unsure"),
        ("not_a_fit", "Not a fit"),
        ("paperwork_pending", "Paperwork pending"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="thread_states")
    thread = models.ForeignKey("MessageThread", on_delete=models.CASCADE, related_name="states")

    label = models.CharField(max_length=32, choices=LABEL_CHOICES, blank=True, default="")
    in_bin = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "thread")
        indexes = [
            models.Index(fields=["user", "thread"]),
            models.Index(fields=["user", "in_bin"]),
            models.Index(fields=["user", "label"]),
            models.Index(fields=["user", "deleted_at"]),
        ]

    def __str__(self):
        return f"State(user={self.user_id}, thread={self.thread_id}, label={self.label or 'no_status'}, bin={self.in_bin})"


# -------
# Message
# -------
class Message(models.Model):
    TYPE_TEXT = "text"
    TYPE_TENANCY_PROPOSAL = "tenancy_proposal"
    TYPE_TENANCY_UPDATED = "tenancy_updated"
    TYPE_TENANCY_CONFIRMED = "tenancy_confirmed"
    TYPE_TENANCY_CANCELLED = "tenancy_cancelled"

    TYPE_CHOICES = (
        (TYPE_TEXT, "Text"),
        (TYPE_TENANCY_PROPOSAL, "Tenancy proposal"),
        (TYPE_TENANCY_UPDATED, "Tenancy updated"),
        (TYPE_TENANCY_CONFIRMED, "Tenancy confirmed"),
        (TYPE_TENANCY_CANCELLED, "Tenancy cancelled"),
    )

    thread = models.ForeignKey(
        MessageThread,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )

    body = models.TextField()

    message_type = models.CharField(
        max_length=32,
        choices=TYPE_CHOICES,
        default=TYPE_TEXT,
        db_index=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created = models.DateTimeField(auto_now_add=True, db_index=True)
    updated = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["created"]
        indexes = [
            models.Index(fields=["thread", "created"]),
            models.Index(fields=["thread", "updated"]),
        ]

class MessageRead(models.Model):
    message = models.ForeignKey("Message", on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="message_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("message", "user")
        indexes = [
            models.Index(fields=["user", "message"]),
        ]

    def __str__(self):
        return f"Read m#{self.message_id} by {self.user_id} at {self.read_at:%Y-%m-%d %H:%M:%S}"


# ------------
# Notification
# ------------
class Notification(models.Model):
    class Type(models.TextChoices):
        MESSAGE = "message", "Message"



    class Audience(models.TextChoices):
        LANDLORD = "landlord", "Landlord"
        SEEKER = "seeker", "Seeker"
        BOTH = "both", "Both"

    audience = models.CharField(
        max_length=16,
        choices=Audience.choices,
        default=Audience.BOTH,
        db_index=True,
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    type = models.CharField(max_length=32, choices=Type.choices, default=Type.MESSAGE)
    target_type = models.CharField(max_length=50, blank=True, null=True)
    target_id = models.BigIntegerField(blank=True, null=True)

    thread = models.ForeignKey(
        "MessageThread",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )

    title = models.CharField(max_length=120, blank=True, default="")
    body = models.TextField(blank=True, default="")

    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "type", "target_type", "target_id"],
                condition=Q(
                    type="review_available",
                    target_type="tenancy_review",
                    target_id__isnull=False,
                ),
                name="uq_notification_review_per_user_tenancy",
            ),
        ]
    
    def __str__(self):
        return f"Notif#{self.pk} to {getattr(self.user, 'username', self.user_id)} [{self.type}]"


# -------
# Payment
# -------
class Payment(models.Model):
    class Provider(models.TextChoices):
        STRIPE = "stripe", "Stripe"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        REQUIRES_PAYMENT = "requires_payment_method", "Requires payment"
        REQUIRES_ACTION = "requires_action", "Requires action"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        CANCELED = "canceled", "Canceled"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payments")
    room = models.ForeignKey("Room", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")

    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.STRIPE)
    amount = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=10, default="GBP")

    stripe_payment_intent_id = models.CharField(max_length=200, blank=True, default="")
    stripe_checkout_session_id = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(max_length=40, choices=Status.choices, default=Status.REQUIRES_PAYMENT)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["room", "created_at"]),
            models.Index(fields=["stripe_payment_intent_id"]),
            models.Index(fields=["stripe_checkout_session_id"]),
        ]

    def __str__(self):
        who = getattr(self.user, "username", self.user_id)
        return f"Payment {self.id} {self.amount} {self.currency} by {who} [{self.status}]"


# ----------------
# GDPR / Privacy
# ----------------
class Report(models.Model):
    TARGET_CHOICES = (
        ("room", "Room"),
        ("review", "Review"),
        ("message", "Message"),
        ("user", "User"),
    )
    STATUS_CHOICES = (
        ("open", "Open"),
        ("in_review", "In review"),
        ("resolved", "Resolved"),
        ("rejected", "Rejected"),
    )

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    target_type = models.CharField(max_length=16, choices=TARGET_CHOICES)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    reason = models.CharField(max_length=64)
    details = models.TextField(blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="handled_reports",
    )
    resolution_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["target_type", "object_id"]),
            models.Index(fields=["created_at"]),
        ]

    @classmethod
    def can_transition_status(cls, current: str, new: str) -> bool:
        """
        Enforce the moderation report status lifecycle.

        Allowed transitions:
        open -> in_review/resolved/rejected
        in_review -> resolved/rejected
        resolved -> terminal
        rejected -> terminal

        Same-status updates are allowed as no-op updates.
        """
        if not current or not new:
            return False

        if current == new:
            return True

        allowed = {
            "open": {"in_review", "resolved", "rejected"},
            "in_review": {"resolved", "rejected"},
            "resolved": set(),
            "rejected": set(),
        }
        return new in allowed.get(current, set())

    def transition_to(self, new_status: str, *, handled_by=None, resolution_notes: str = "") -> None:
        """
        Safely transition this report to a new moderation status.
        """
        if not self.can_transition_status(self.status, new_status):
            raise ValidationError(f"Invalid transition from '{self.status}' to '{new_status}'.")

        if resolution_notes:
            self.resolution_notes = resolution_notes

        self.status = new_status

        if handled_by is not None:
            self.handled_by = handled_by

        self.save(update_fields=["status", "resolution_notes", "handled_by", "updated_at"])

    def __str__(self):
        return f"Report #{self.pk} {self.target_type}:{self.object_id} ({self.status})"


class DataExport(models.Model):
    STATUS_CHOICES = (
        ("queued", "queued"),
        ("processing", "processing"),
        ("ready", "ready"),
        ("failed", "failed"),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="data_exports")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    file_path = models.CharField(max_length=512, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    def is_expired(self):
        return bool(self.expires_at and timezone.now() >= self.expires_at)


class GDPRTombstone(models.Model):
    user_id_hash = models.CharField(max_length=128)
    anonymised_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True, default="")


# -----
# EmailOTP
# -----
class EmailOTP(models.Model):
    PURPOSE_EMAIL_VERIFY = "email_verify"
    PURPOSE_PASSWORD_RESET = "password_reset"
    PURPOSE_ACCOUNT_REACTIVATION = "account_reactivation"
    PURPOSE_ACCOUNT_DELETE = "account_delete"

    PURPOSE_CHOICES = [
        (PURPOSE_EMAIL_VERIFY, "Email verification"),
        (PURPOSE_PASSWORD_RESET, "Password reset"),
        (PURPOSE_ACCOUNT_REACTIVATION, "Account reactivation"),
        (PURPOSE_ACCOUNT_DELETE, "Account delete"),
    ]

    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="email_otps")
    purpose = models.CharField(
        max_length=32,
        choices=PURPOSE_CHOICES,
        default=PURPOSE_EMAIL_VERIFY,
    )
    code = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["user", "purpose", "created_at"]),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def matches(self, value: str) -> bool:
        raw = (value or "").strip()
        if not raw:
            return False
        return check_password(raw, self.code)

    def mark_used(self) -> None:
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @classmethod
    def create_for(
        cls,
        user,
        code: str,
        ttl_minutes: int | None = None,
        purpose: str = PURPOSE_EMAIL_VERIFY,
    ):
        ttl_minutes = (
            settings.OTP_EXPIRY_MINUTES if ttl_minutes is None else ttl_minutes
        )
        expires_at = timezone.now() + timedelta(minutes=ttl_minutes)
        return cls.objects.create(
            user=user,
            purpose=purpose,
            code=make_password(str(code).strip()),
            expires_at=expires_at,
        )

# -----
# PhoneOTP
# -----
class PhoneOTP(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="phone_otps")
    phone = models.CharField(max_length=15)
    code = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["phone", "created_at"]),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_used(self) -> bool:
        return self.used_at is not None


    def matches(self, value: str) -> bool:
        raw = (value or "").strip()
        if not raw:
            return False
        return check_password(raw, self.code)

    def mark_used(self) -> None:
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @classmethod
    def create_for(cls, *, user, phone: str, code: str, ttl_minutes: int | None = None):
        ttl_minutes = settings.OTP_EXPIRY_MINUTES if ttl_minutes is None else ttl_minutes
        expires_at = timezone.now() + timedelta(minutes=ttl_minutes)
        return cls.objects.create(
            user=user,
            phone=phone,
            code=make_password(str(code).strip()),
            expires_at=expires_at,
        )


