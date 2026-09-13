from django.core.management.base import BaseCommand

from propertylist_app.models import City
from propertylist_app.services.city_images import (
    prepare_city_image,
    remove_embedded_city_image_footer,
)


class Command(BaseCommand):
    help = "Remove the legacy embedded black attribution footer from city-card images."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        cleaned = 0
        skipped = 0
        for city in City.objects.filter(is_active=True).exclude(image="").order_by("display_order", "pk"):
            with city.image.open("rb") as source:
                upload = remove_embedded_city_image_footer(source)
            if upload is None:
                skipped += 1
                continue
            cleaned += 1
            if not options["apply"]:
                continue

            old_storage = city.image.storage
            old_name = city.image.name
            prepared = prepare_city_image(upload)
            city.image.save(f"{city.slug}-clean.jpg", prepared, save=False)
            new_name = city.image.name
            city.save(update_fields=["image", "updated_at"])
            if old_name != new_name:
                old_storage.delete(old_name)

        mode = "applied" if options["apply"] else "dry-run"
        self.stdout.write(f"City image footer cleanup ({mode}): cleaned={cleaned}, skipped={skipped}")
