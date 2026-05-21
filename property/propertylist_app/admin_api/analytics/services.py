from .selectors import (
    get_listing_growth_data,
    get_booking_trends_data,
    get_payment_status_mix_data,
    get_moderation_backlog_trends_data,
)


def get_listing_growth_chart_data():
    return {
        "listing_growth": get_listing_growth_data(),
    }
    
    
def get_booking_trends_chart_data():
    return {
        "booking_trends": get_booking_trends_data(),
    }  
    
    
def get_payment_status_mix_chart_data():
    return {
        "payment_status_mix": get_payment_status_mix_data(),
    }      
    
    
def get_moderation_backlog_trends_chart_data():
    return {
        "moderation_backlog_trends": get_moderation_backlog_trends_data(),
    }    