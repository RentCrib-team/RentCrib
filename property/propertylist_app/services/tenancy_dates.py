from datetime import datetime, timedelta, time
from dateutil.relativedelta import relativedelta
from django.utils import timezone


def compute_end_date(move_in_date, duration_months):
    # accurate calendar month maths
    return move_in_date + relativedelta(months=+int(duration_months))


def compute_review_window(move_in_date, duration_months):
    end_date = compute_end_date(move_in_date, duration_months)

    # use midnight of end_date in current timezone to keep dates stable
    end_midnight = timezone.make_aware(datetime.combine(end_date, time.min))


        # -------------------------------------------------
    # PRODUCTION RULES - KEEP FOR RESTORATION AFTER QA
    # -------------------------------------------------

    # Review window opens 7 days after tenancy ends.
    # review_open_at = end_midnight + timedelta(days=7)

    # Review window remains open for 30 days.
    # review_deadline_at = review_open_at + timedelta(days=30)

    # Still-living reminder is sent 7 days before tenancy ends.
    # still_living_check_at = end_midnight - timedelta(days=7)


    # -------------------------------------------------
    # TEMPORARY QA RULES
    # -------------------------------------------------

    # Open the review window 10 minutes after tenancy ends.
    review_open_at = end_midnight + timedelta(minutes=10)

    # Keep the private/double-blind review window open for 10 minutes.
    review_deadline_at = review_open_at + timedelta(minutes=10)

    # Keep the production still-living timing for now.
    still_living_check_at = end_midnight - timedelta(days=7)

    return review_open_at, review_deadline_at, still_living_check_at