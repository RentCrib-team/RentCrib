from .selectors import get_listing_growth_data


def get_listing_growth_chart_data():
    return {
        "listing_growth": get_listing_growth_data(),
    }