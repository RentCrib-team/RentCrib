"""Canonical UK city catalogue used to seed RentCrib city browsing.

Source: Cabinet Office, GOV.UK, "List of cities", published 29 August 2022.
The official list contains two cities called Bangor (one in Wales and one in
Northern Ireland). Because the current City model requires a unique name, those
two database records use a nation qualifier internally while retaining the
public display name "Bangor" and distinct slugs.
"""


OFFICIAL_UK_CITIES = (
    # England
    {"name": "Bath", "display_name": "Bath", "slug": "bath", "nation": "England"},
    {"name": "Birmingham", "display_name": "Birmingham", "slug": "birmingham", "nation": "England"},
    {"name": "Bradford", "display_name": "Bradford", "slug": "bradford", "nation": "England"},
    {"name": "Brighton & Hove", "display_name": "Brighton & Hove", "slug": "brighton-hove", "nation": "England"},
    {"name": "Bristol", "display_name": "Bristol", "slug": "bristol", "nation": "England"},
    {"name": "Cambridge", "display_name": "Cambridge", "slug": "cambridge", "nation": "England"},
    {"name": "Canterbury", "display_name": "Canterbury", "slug": "canterbury", "nation": "England"},
    {"name": "Carlisle", "display_name": "Carlisle", "slug": "carlisle", "nation": "England"},
    {"name": "Chelmsford", "display_name": "Chelmsford", "slug": "chelmsford", "nation": "England"},
    {"name": "Chester", "display_name": "Chester", "slug": "chester", "nation": "England"},
    {"name": "Chichester", "display_name": "Chichester", "slug": "chichester", "nation": "England"},
    {"name": "Colchester", "display_name": "Colchester", "slug": "colchester", "nation": "England"},
    {"name": "Coventry", "display_name": "Coventry", "slug": "coventry", "nation": "England"},
    {"name": "Derby", "display_name": "Derby", "slug": "derby", "nation": "England"},
    {"name": "Doncaster", "display_name": "Doncaster", "slug": "doncaster", "nation": "England"},
    {"name": "Durham", "display_name": "Durham", "slug": "durham", "nation": "England"},
    {"name": "Ely", "display_name": "Ely", "slug": "ely", "nation": "England"},
    {"name": "Exeter", "display_name": "Exeter", "slug": "exeter", "nation": "England"},
    {"name": "Gloucester", "display_name": "Gloucester", "slug": "gloucester", "nation": "England"},
    {"name": "Hereford", "display_name": "Hereford", "slug": "hereford", "nation": "England"},
    {"name": "Kingston-upon-Hull", "display_name": "Kingston-upon-Hull", "slug": "kingston-upon-hull", "nation": "England"},
    {"name": "Lancaster", "display_name": "Lancaster", "slug": "lancaster", "nation": "England"},
    {"name": "Leeds", "display_name": "Leeds", "slug": "leeds", "nation": "England"},
    {"name": "Leicester", "display_name": "Leicester", "slug": "leicester", "nation": "England"},
    {"name": "Lichfield", "display_name": "Lichfield", "slug": "lichfield", "nation": "England"},
    {"name": "Lincoln", "display_name": "Lincoln", "slug": "lincoln", "nation": "England"},
    {"name": "Liverpool", "display_name": "Liverpool", "slug": "liverpool", "nation": "England"},
    {"name": "London", "display_name": "London", "slug": "london", "nation": "England"},
    {"name": "Manchester", "display_name": "Manchester", "slug": "manchester", "nation": "England"},
    {"name": "Milton Keynes", "display_name": "Milton Keynes", "slug": "milton-keynes", "nation": "England"},
    {"name": "Newcastle-upon-Tyne", "display_name": "Newcastle-upon-Tyne", "slug": "newcastle-upon-tyne", "nation": "England"},
    {"name": "Norwich", "display_name": "Norwich", "slug": "norwich", "nation": "England"},
    {"name": "Nottingham", "display_name": "Nottingham", "slug": "nottingham", "nation": "England"},
    {"name": "Oxford", "display_name": "Oxford", "slug": "oxford", "nation": "England"},
    {"name": "Peterborough", "display_name": "Peterborough", "slug": "peterborough", "nation": "England"},
    {"name": "Plymouth", "display_name": "Plymouth", "slug": "plymouth", "nation": "England"},
    {"name": "Portsmouth", "display_name": "Portsmouth", "slug": "portsmouth", "nation": "England"},
    {"name": "Preston", "display_name": "Preston", "slug": "preston", "nation": "England"},
    {"name": "Ripon", "display_name": "Ripon", "slug": "ripon", "nation": "England"},
    {"name": "Salford", "display_name": "Salford", "slug": "salford", "nation": "England"},
    {"name": "Salisbury", "display_name": "Salisbury", "slug": "salisbury", "nation": "England"},
    {"name": "Sheffield", "display_name": "Sheffield", "slug": "sheffield", "nation": "England"},
    {"name": "Southampton", "display_name": "Southampton", "slug": "southampton", "nation": "England"},
    {"name": "Southend-on-Sea", "display_name": "Southend-on-Sea", "slug": "southend-on-sea", "nation": "England"},
    {"name": "St Albans", "display_name": "St Albans", "slug": "st-albans", "nation": "England"},
    {"name": "Stoke on Trent", "display_name": "Stoke on Trent", "slug": "stoke-on-trent", "nation": "England"},
    {"name": "Sunderland", "display_name": "Sunderland", "slug": "sunderland", "nation": "England"},
    {"name": "Truro", "display_name": "Truro", "slug": "truro", "nation": "England"},
    {"name": "Wakefield", "display_name": "Wakefield", "slug": "wakefield", "nation": "England"},
    {"name": "Wells", "display_name": "Wells", "slug": "wells", "nation": "England"},
    {"name": "Westminster", "display_name": "Westminster", "slug": "westminster", "nation": "England"},
    {"name": "Winchester", "display_name": "Winchester", "slug": "winchester", "nation": "England"},
    {"name": "Wolverhampton", "display_name": "Wolverhampton", "slug": "wolverhampton", "nation": "England"},
    {"name": "Worcester", "display_name": "Worcester", "slug": "worcester", "nation": "England"},
    {"name": "York", "display_name": "York", "slug": "york", "nation": "England"},

    # Northern Ireland
    {"name": "Armagh", "display_name": "Armagh", "slug": "armagh", "nation": "Northern Ireland"},
    {"name": "Bangor (Northern Ireland)", "display_name": "Bangor", "slug": "bangor-northern-ireland", "nation": "Northern Ireland"},
    {"name": "Belfast", "display_name": "Belfast", "slug": "belfast", "nation": "Northern Ireland"},
    {"name": "Lisburn", "display_name": "Lisburn", "slug": "lisburn", "nation": "Northern Ireland"},
    {"name": "Londonderry", "display_name": "Londonderry", "slug": "londonderry", "nation": "Northern Ireland"},
    {"name": "Newry", "display_name": "Newry", "slug": "newry", "nation": "Northern Ireland"},

    # Scotland
    {"name": "Aberdeen", "display_name": "Aberdeen", "slug": "aberdeen", "nation": "Scotland"},
    {"name": "Dundee", "display_name": "Dundee", "slug": "dundee", "nation": "Scotland"},
    {"name": "Dunfermline", "display_name": "Dunfermline", "slug": "dunfermline", "nation": "Scotland"},
    {"name": "Edinburgh", "display_name": "Edinburgh", "slug": "edinburgh", "nation": "Scotland"},
    {"name": "Glasgow", "display_name": "Glasgow", "slug": "glasgow", "nation": "Scotland"},
    {"name": "Inverness", "display_name": "Inverness", "slug": "inverness", "nation": "Scotland"},
    {"name": "Perth", "display_name": "Perth", "slug": "perth", "nation": "Scotland"},
    {"name": "Stirling", "display_name": "Stirling", "slug": "stirling", "nation": "Scotland"},

    # Wales
    {"name": "Bangor (Wales)", "display_name": "Bangor", "slug": "bangor-wales", "nation": "Wales"},
    {"name": "Cardiff", "display_name": "Cardiff", "slug": "cardiff", "nation": "Wales"},
    {"name": "Newport", "display_name": "Newport", "slug": "newport", "nation": "Wales"},
    {"name": "St Asaph", "display_name": "St Asaph", "slug": "st-asaph", "nation": "Wales"},
    {"name": "St Davids", "display_name": "St Davids", "slug": "st-davids", "nation": "Wales"},
    {"name": "Swansea", "display_name": "Swansea", "slug": "swansea", "nation": "Wales"},
    {"name": "Wrexham", "display_name": "Wrexham", "slug": "wrexham", "nation": "Wales"},
)

OFFICIAL_UK_CITY_COUNT = 76
SOUTHAMPTON_SLUG = "southampton"
BANGOR_SLUGS = frozenset({"bangor-northern-ireland", "bangor-wales"})
