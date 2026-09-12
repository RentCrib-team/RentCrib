from django.core.management.base import BaseCommand
from django.db.models import Q

from propertylist_app.models import City


class Command(BaseCommand):
    help = "Report city image coverage and list cities still using the fallback image."

    def handle(self, *args, **options):
        cities = City.objects.all().order_by("display_order", "name")
        missing_filter = Q(image__isnull=True) | Q(image="")

        total = cities.count()
        missing = cities.filter(missing_filter)
        with_image = total - missing.count()
        featured_missing = missing.filter(is_featured=True).count()

        self.stdout.write(f"Total cities: {total}")
        self.stdout.write(f"With uploaded image: {with_image}")
        self.stdout.write(f"Using fallback image: {missing.count()}")
        self.stdout.write(f"Featured cities missing image: {featured_missing}")

        if missing.exists():
            self.stdout.write("\nCities still using fallback:")
            for city in missing:
                self.stdout.write(f"- {city.name} ({city.slug})")
