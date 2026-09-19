import celery_app as runtime_celery_app


def test_listing_expiry_warning_and_expiry_schedules_are_disabled():
    schedule = runtime_celery_app.app.conf.beat_schedule

    assert "listing-expiry-warning-sweep-every-minute" not in schedule
    assert "listing-expiry-sweep-every-minute" not in schedule
    assert all(
        entry.get("task")
        not in {
            "propertylist_app.listing_expiry_warning_sweep",
            "propertylist_app.listing_expiry_sweep",
        }
        for entry in schedule.values()
    )
