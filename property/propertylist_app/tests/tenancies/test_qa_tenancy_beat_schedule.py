import celery_app as runtime_celery_app


def test_accelerated_qa_tenancy_schedule_uses_single_clock():
    schedule = runtime_celery_app.app.conf.beat_schedule

    qa_sweep = schedule["tenancy-prompts-sweep-every-minute"]
    assert qa_sweep["task"] == (
        "propertylist_app.tasks.task_tenancy_prompts_sweep"
    )

    # HARD QA CONTRACT:
    # The real-calendar daily tenancy reconciliation must not run alongside
    # the accelerated minute-by-minute lifecycle. Otherwise legacy rows can
    # be ended from their actual tenancy date or receive schedule fields from
    # compute_review_window() before Timer 2 has completed.
    assert "refresh-tenancy-status-and-review-windows-daily" not in schedule
    assert all(
        entry.get("task")
        != "propertylist_app.tasks.task_refresh_tenancy_status_and_review_windows"
        for entry in schedule.values()
    )
