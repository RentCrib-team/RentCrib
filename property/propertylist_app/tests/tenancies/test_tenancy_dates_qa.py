from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from propertylist_app.services.tenancy_dates import compute_end_date, compute_review_window


@pytest.mark.django_db
def test_qa_tenancy_lifecycle_schedule_uses_minutes_only():
    """Temporary QA lifecycle timings must not retain production day-based delays."""
    move_in_date = timezone.localdate()
    duration_months = 1

    end_date = compute_end_date(move_in_date, duration_months)
    end_midnight = timezone.make_aware(
        datetime.combine(end_date, time.min),
        timezone.get_current_timezone(),
    )

    review_open_at, review_deadline_at, still_living_check_at = compute_review_window(
        move_in_date,
        duration_months,
    )

    assert review_open_at - end_midnight == timedelta(minutes=10)
    assert review_deadline_at - review_open_at == timedelta(minutes=10)
    assert end_midnight - still_living_check_at == timedelta(minutes=10)
