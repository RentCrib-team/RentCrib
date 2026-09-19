from django.core.management.base import BaseCommand

from propertylist_app.models import RoomImage
from propertylist_app.services.image import build_listing_thumbnail


class Command(BaseCommand):
    help = "Generate missing 640px card thumbnails for existing room photos."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options):
        queryset = RoomImage.objects.filter(
            image__isnull=False,
            thumbnail__isnull=True,
        ).order_by("id")
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        created = 0
        failed = 0
        for room_image in queryset.iterator(chunk_size=50):
            try:
                with room_image.image.open("rb") as source:
                    thumbnail = build_listing_thumbnail(source)
                room_image.thumbnail.save(
                    thumbnail.name,
                    thumbnail,
                    save=True,
                )
                created += 1
            except Exception as exc:
                failed += 1
                self.stderr.write(
                    f"RoomImage {room_image.pk}: {exc.__class__.__name__}: {exc}"
                )

        self.stdout.write(self.style.SUCCESS(f"created={created} failed={failed}"))
