"""
Shared unread-computation helpers for messaging.

The "what counts as unread" rule is duplicated across the REST views and the
realtime payload emitters, and each copy has silently drifted before (see
BUG 12 — the frontend's enforced view of the envelope disagreed with the
backend's). This module is the single definition:

    * a message is unread for ``user`` when it is a RentCrib system event, or
      was sent by another participant, and the user has no ``MessageRead`` row
      for it;
    * binned threads (per-user ``MessageThreadState.in_bin``) never count
      toward any total or conversation count a badge, inbox or realtime event
      should produce.

Totals are computed at three granularities, matching what the frontend
actually renders (see BE-03):

    * account-wide  — every non-binned thread the user participates in
    * role-scoped   — threads where ``landlord == user`` (landlord) or
      ``seeker == user`` (seeker); unscoped threads count in *both* totals,
      matching how `getThreads` shows them under both roles
    * conversation  — every non-binned thread sharing one ``room_id`` (the
      frontend's ``relationshipId`` / ``relationship_id``, see BE-01)

Realtime events are state-transfer now: they carry the conversation total and
the role totals straight off these helpers, so the frontend writes the numbers
instead of recomputing the merged sum itself (see BE-03).
"""

from django.db.models import Count, Q

from propertylist_app.models import Message, MessageThread, MessageThreadState


def unread_filter(user, prefix=""):
    """
    The "is this message unread for `user`" test, as a Q expression.

    ``prefix`` lets an annotation running against the joined relation (e.g.
    ``Count("messages", filter=unread_filter(user, "messages__"))``) reuse the
    exact same rule instead of restating it field-prefixed.
    """
    return (
        Q(**{f"{prefix}metadata__system_event": True})
        | ~Q(**{f"{prefix}sender": user})
    )


def unread_read_exclusion(user, prefix=""):
    """The read-marker half of the unread test (excluding read rows)."""
    return ~Q(**{f"{prefix}reads__user": user})


def bin_thread_ids(user):
    """Thread ids this user has binned — never counted as unread."""
    return list(
        MessageThreadState.objects
        .filter(user=user, in_bin=True)
        .values_list("thread_id", flat=True)
    )


def base_threads_for_user(user, bin_ids=None):
    """Every thread the user participates in, binned ones excluded."""
    qs = MessageThread.objects.filter(participants=user)
    if bin_ids is None:
        bin_ids = bin_thread_ids(user)
    if bin_ids:
        qs = qs.exclude(id__in=bin_ids)
    return qs


def threads_for_role(user, role):
    """
    Non-binned threads belonging to one role's inbox.

    ``role`` is "landlord" or "seeker". Unscoped threads (see
    ``participant_role``) count in *both* role sets — exactly how
    ``getThreads``' role filter already surfaces them — so a legacy or
    dual-role thread keeps its unread visible from either hat instead of
    vanishing from one of them (see BE-03 decision 2).
    """
    base = base_threads_for_user(user)
    if role == "landlord":
        return base.filter(landlord=user)
    if role == "seeker":
        return base.filter(seeker=user)
    raise ValueError(f"Unknown role: {role!r}")


def _participant_user_id(user):
    """Accept a User instance or a raw user id."""
    return getattr(user, "id", user)


def participant_role(user, thread):
    """
    Which hat the user wears on ``thread``: "landlord", "seeker" or
    "unscoped". Two hats (or none — a pre-BE-01 roomless thread) is never a
    guess from message order/text; it is explicitly "unscoped", the same rule
    the MessageThreadSerializer uses (see get_participant_role).
    """
    user_id = _participant_user_id(user)
    matching_roles = []

    if thread.landlord_id == user_id:
        matching_roles.append("landlord")

    if thread.seeker_id == user_id:
        matching_roles.append("seeker")

    if len(matching_roles) == 1:
        return matching_roles[0]

    return "unscoped"


def unread_messages(user, threads_qs):
    """The user's unread messages across ``threads_qs`` (binned already gone)."""
    return (
        Message.objects
        .filter(thread__in=threads_qs)
        .filter(unread_filter(user))
        .exclude(reads__user=user)
        .distinct()
    )


def unread_totals(user, bin_ids=None):
    """
    Account-wide and both per-role unread totals in one aggregate.

    Returns a dict::

        {"account": int, "landlord": int, "seeker": int}

    Unscoped threads appear in both role totals (see ``threads_for_role``), so
    ``account`` is not a sum of the two roles — a thread counted under both
    hats still only contributes once to the account total.
    """
    rows = (
        unread_messages(user, base_threads_for_user(user, bin_ids=bin_ids))
        .aggregate(
            account=Count("id", distinct=True),
            landlord=Count(
                "id",
                filter=Q(thread__landlord=user),
                distinct=True,
            ),
            seeker=Count(
                "id",
                filter=Q(thread__seeker=user),
                distinct=True,
            ),
        )
    )
    return {
        "account": rows["account"] or 0,
        "landlord": rows["landlord"] or 0,
        "seeker": rows["seeker"] or 0,
    }


def conversation_threads(user, relationship_id, bin_ids=None):
    """Non-binned threads for one conversation (one ``room_id``)."""
    return base_threads_for_user(user, bin_ids=bin_ids).filter(room_id=relationship_id)


def conversation_unread_count(user, relationship_id, bin_ids=None):
    """The user's unread total across one conversation (one room)."""
    if relationship_id is None:
        return 0
    return unread_messages(user, conversation_threads(user, relationship_id, bin_ids=bin_ids)).count()


def conversation_unread_counts(user, relationship_ids, bin_ids=None):
    """
    Unread totals keyed by ``relationship_id`` for several conversations.

    Used by the bulk mark-read event, which may touch threads across several
    rooms in one call — one aggregated query instead of N.
    """
    ids = [rid for rid in relationship_ids if rid is not None]

    if not ids:
        return {}

    rows = (
        unread_messages(user, base_threads_for_user(user, bin_ids=bin_ids).filter(room_id__in=ids))
        .values("thread__room_id")
        .annotate(total=Count("id", distinct=True))
    )

    return {
        row["thread__room_id"]: row["total"]
        for row in rows
    }