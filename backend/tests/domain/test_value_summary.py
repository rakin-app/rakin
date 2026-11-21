"""The Resumen del mes rules (#505, `app.domain.value_summary`), with no database."""

from datetime import UTC, date, datetime, timedelta

from app.domain.value_summary import (
    AfterReminder,
    Channel,
    LatePayment,
    Nudge,
    Reminder,
    after_reminder,
    came_back,
    first_nudges,
    percent,
    share_of_income,
)

DUE = date(2026, 9, 10)


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


def email(day: date, hour: int = 12) -> Reminder:
    return Reminder(Channel.EMAIL, at(day, hour), day)


def whatsapp(day: date, hour: int = 12) -> Reminder:
    return Reminder(Channel.WHATSAPP, at(day, hour), day)


def paid(day: date, *reminders: Reminder, hour: int = 15) -> LatePayment:
    return LatePayment(due_date=DUE, paid_at=at(day, hour), paid_on=day, reminders=reminders)


def day(n: int) -> date:
    """`n` days after the due date."""
    return DUE + timedelta(days=n)


def test_a_payment_on_the_due_date_is_on_time() -> None:
    assert after_reminder(paid(DUE, email(day(-1)))) is None


def test_a_late_payment_with_no_reminder_before_it_does_not_count() -> None:
    assert after_reminder(paid(day(3))) is None


def test_a_reminder_after_the_payment_does_not_count() -> None:
    assert after_reminder(paid(day(4), email(day(4), hour=20))) is None
    assert after_reminder(paid(day(4), email(day(5)))) is None


def test_a_reminder_on_the_due_date_never_counts() -> None:
    # The day-0 email and WhatsApp's `payment_due_today` are both sent on the due date.
    assert after_reminder(paid(day(1), email(DUE, hour=23), whatsapp(DUE))) is None


def test_a_day_1_email_then_a_payment_counts_as_emails_only() -> None:
    assert after_reminder(paid(day(2), email(DUE), email(day(1)))) is AfterReminder.EMAILS_ONLY


def test_a_whatsapp_then_an_email_then_a_payment_counts_as_after_whatsapp() -> None:
    payment = paid(day(5), whatsapp(day(2)), email(day(4)))
    assert after_reminder(payment) is AfterReminder.AFTER_WHATSAPP


def test_a_whatsapp_opened_after_the_payment_leaves_it_emails_only() -> None:
    payment = paid(day(5), email(day(4)), whatsapp(day(6)))
    assert after_reminder(payment) is AfterReminder.EMAILS_ONLY


def nudge(about: str, on: date, first_class_on: date | None, hour: int = 10) -> Nudge:
    return Nudge(about=about, sent_at=at(on, hour), sent_on=on, first_class_on=first_class_on)


def test_someone_nudged_twice_is_counted_once_from_the_first() -> None:
    later = nudge("a", day(8), day(9))
    first = nudge("a", day(1), None)
    other = nudge("b", day(3), None)

    assert first_nudges([later, first, other]) == [first, other]


def test_back_within_14_days_counts_and_day_15_does_not() -> None:
    assert came_back(nudge("a", DUE, DUE))
    assert came_back(nudge("a", DUE, day(14)))
    assert not came_back(nudge("a", DUE, day(15)))
    assert not came_back(nudge("a", DUE, None))


def test_no_percentage_under_5() -> None:
    assert percent(1, 3) is None
    assert percent(1, 4) is None
    assert percent(2, 5) == 40
    assert percent(0, 0) is None
    assert percent(6, 5) is None


def test_a_share_of_income_needs_5_payments_and_never_passes_it() -> None:
    assert share_of_income(18_000, 100_000, 4) is None
    assert share_of_income(18_000, 100_000, 5) == 18
    assert share_of_income(0, 0, 9) is None
    assert share_of_income(120_000, 100_000, 9) is None
