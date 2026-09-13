from django.db import migrations
from django.db.models import Q


# Keep historical migration data self-contained. Runtime catalogue files may be
# extended later, but a fresh database must always replay migration 0100 with
# the exact same 76-city dataset that originally shipped with this migration.
SEEDED_UK_CITIES = (
    ("Bath", "bath", "Bath"),
    ("Birmingham", "birmingham", "Birmingham"),
    ("Bradford", "bradford", "Bradford"),
    ("Brighton & Hove", "brighton-hove", "Brighton & Hove"),
    ("Bristol", "bristol", "Bristol"),
    ("Cambridge", "cambridge", "Cambridge"),
    ("Canterbury", "canterbury", "Canterbury"),
    ("Carlisle", "carlisle", "Carlisle"),
    ("Chelmsford", "chelmsford", "Chelmsford"),
    ("Chester", "chester", "Chester"),
    ("Chichester", "chichester", "Chichester"),
    ("Colchester", "colchester", "Colchester"),
    ("Coventry", "coventry", "Coventry"),
    ("Derby", "derby", "Derby"),
    ("Doncaster", "doncaster", "Doncaster"),
    ("Durham", "durham", "Durham"),
    ("Ely", "ely", "Ely"),
    ("Exeter", "exeter", "Exeter"),
    ("Gloucester", "gloucester", "Gloucester"),
    ("Hereford", "hereford", "Hereford"),
    ("Kingston-upon-Hull", "kingston-upon-hull", "Kingston-upon-Hull"),
    ("Lancaster", "lancaster", "Lancaster"),
    ("Leeds", "leeds", "Leeds"),
    ("Leicester", "leicester", "Leicester"),
    ("Lichfield", "lichfield", "Lichfield"),
    ("Lincoln", "lincoln", "Lincoln"),
    ("Liverpool", "liverpool", "Liverpool"),
    ("London", "london", "London"),
    ("Manchester", "manchester", "Manchester"),
    ("Milton Keynes", "milton-keynes", "Milton Keynes"),
    ("Newcastle-upon-Tyne", "newcastle-upon-tyne", "Newcastle-upon-Tyne"),
    ("Norwich", "norwich", "Norwich"),
    ("Nottingham", "nottingham", "Nottingham"),
    ("Oxford", "oxford", "Oxford"),
    ("Peterborough", "peterborough", "Peterborough"),
    ("Plymouth", "plymouth", "Plymouth"),
    ("Portsmouth", "portsmouth", "Portsmouth"),
    ("Preston", "preston", "Preston"),
    ("Ripon", "ripon", "Ripon"),
    ("Salford", "salford", "Salford"),
    ("Salisbury", "salisbury", "Salisbury"),
    ("Sheffield", "sheffield", "Sheffield"),
    ("Southampton", "southampton", "Southampton"),
    ("Southend-on-Sea", "southend-on-sea", "Southend-on-Sea"),
    ("St Albans", "st-albans", "St Albans"),
    ("Stoke on Trent", "stoke-on-trent", "Stoke on Trent"),
    ("Sunderland", "sunderland", "Sunderland"),
    ("Truro", "truro", "Truro"),
    ("Wakefield", "wakefield", "Wakefield"),
    ("Wells", "wells", "Wells"),
    ("Westminster", "westminster", "Westminster"),
    ("Winchester", "winchester", "Winchester"),
    ("Wolverhampton", "wolverhampton", "Wolverhampton"),
    ("Worcester", "worcester", "Worcester"),
    ("York", "york", "York"),
    ("Armagh", "armagh", "Armagh"),
    ("Bangor (Northern Ireland)", "bangor-northern-ireland", "Bangor"),
    ("Belfast", "belfast", "Belfast"),
    ("Lisburn", "lisburn", "Lisburn"),
    ("Londonderry", "londonderry", "Londonderry"),
    ("Newry", "newry", "Newry"),
    ("Aberdeen", "aberdeen", "Aberdeen"),
    ("Dundee", "dundee", "Dundee"),
    ("Dunfermline", "dunfermline", "Dunfermline"),
    ("Edinburgh", "edinburgh", "Edinburgh"),
    ("Glasgow", "glasgow", "Glasgow"),
    ("Inverness", "inverness", "Inverness"),
    ("Perth", "perth", "Perth"),
    ("Stirling", "stirling", "Stirling"),
    ("Bangor (Wales)", "bangor-wales", "Bangor"),
    ("Cardiff", "cardiff", "Cardiff"),
    ("Newport", "newport", "Newport"),
    ("St Asaph", "st-asaph", "St Asaph"),
    ("St Davids", "st-davids", "St Davids"),
    ("Swansea", "swansea", "Swansea"),
    ("Wrexham", "wrexham", "Wrexham"),
)

SOUTHAMPTON_SLUG = "southampton"


def seed_official_uk_cities(apps, schema_editor):
    City = apps.get_model("propertylist_app", "City")

    for position, (name, slug, display_name) in enumerate(SEEDED_UK_CITIES, start=1):
        city = City.objects.filter(slug=slug).first()

        if city is None and not name.startswith("Bangor ("):
            city = City.objects.filter(name__iexact=name).first()

        if city is not None:
            continue

        is_southampton = slug == SOUTHAMPTON_SLUG
        City.objects.create(
            name=name,
            slug=slug,
            image_alt=display_name,
            is_active=True,
            is_featured=is_southampton,
            display_order=1 if is_southampton else 100 + position,
        )


def unseed_official_uk_cities(apps, schema_editor):
    City = apps.get_model("propertylist_app", "City")
    Room = apps.get_model("propertylist_app", "Room")

    for position, (name, slug, display_name) in enumerate(SEEDED_UK_CITIES, start=1):
        is_southampton = slug == SOUTHAMPTON_SLUG
        expected_order = 1 if is_southampton else 100 + position

        city = (
            City.objects.filter(
                slug=slug,
                name=name,
                image_alt=display_name,
                is_active=True,
                is_featured=is_southampton,
                display_order=expected_order,
            )
            .filter(Q(image__isnull=True) | Q(image=""))
            .first()
        )

        if city is None:
            continue
        if Room.objects.filter(city_id=city.id).exists():
            continue

        city.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0099_city_room_city"),
    ]

    operations = [
        migrations.RunPython(
            seed_official_uk_cities,
            reverse_code=unseed_official_uk_cities,
        ),
    ]
