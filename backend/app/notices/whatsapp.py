"""The WhatsApp messages Rakin writes for the admin to send, in Spanish.

v1 sends none itself: each is prefilled in a `wa.me` link (`app.integrations.messenger`)
that the admin opens from one of their lists, and recorded in `message_log` as they
open it (migration 0024). Each template has a name, the row's `template`.

They are short and plain text, as a WhatsApp message is, and greet by first name.
"""

from datetime import date

from app.domain.money import format_clp

INACTIVE_NUDGE = "inactive_nudge"


def first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def inactive_nudge(
    *, to_name: str, about_name: str | None, gym_name: str, days_absent: int, attended: bool
) -> str:
    """The nudge to someone who stopped coming (#50), or to their guardian
    (`about_name`, the dependent's name) when it is about a dependent. `attended` is
    false for someone who has not come to a class yet."""
    hello = f"Hola {first_name(to_name)}"
    if about_name is None:
        gap = (
            f"hace {days_absent} días que no vienes a entrenar"
            if attended
            else "todavía no vienes a tu primera clase"
        )
        return f"{hello}, te echamos de menos en {gym_name}: {gap}. ¿Todo bien? ¡Te esperamos!"
    kid = first_name(about_name)
    gap = (
        f"hace {days_absent} días que no viene a entrenar"
        if attended
        else "todavía no viene a su primera clase"
    )
    return f"{hello}, echamos de menos a {kid} en {gym_name}: {gap}. ¿Todo bien? ¡Los esperamos!"


# The payment reminders (#55): on the due date, then every `reminder_every_days` while
# overdue, and the follow-up to a rejected proof. One per billing period at a time.
PAYMENT_DUE_TODAY = "payment_due_today"
PAYMENT_OVERDUE = "payment_overdue"
PROOF_REJECTED_FOLLOWUP = "proof_rejected_followup"
PAYMENT_REMINDERS = (PAYMENT_DUE_TODAY, PAYMENT_OVERDUE, PROOF_REJECTED_FOLLOWUP)


def _fecha(value: date) -> str:
    return f"{value:%d-%m-%Y}"


def _whose(about_name: str | None) -> str:
    """`tu pago`, or `el pago de Tomás` for a guardian about a dependent."""
    return "tu pago" if about_name is None else f"el pago de {first_name(about_name)}"


def payment_due_today(
    *, to_name: str, about_name: str | None, gym_name: str, plan_name: str, outstanding_clp: int
) -> str:
    """The reminder on the due date, to them or to their guardian (`about_name`)."""
    return (
        f"Hola {first_name(to_name)}, te recordamos que hoy vence {_whose(about_name)}"
        f" de {plan_name} en {gym_name}: {format_clp(outstanding_clp)}. Si ya pagaste,"
        " envíanos el comprobante. ¡Gracias!"
    )


def payment_overdue(
    *,
    to_name: str,
    about_name: str | None,
    gym_name: str,
    plan_name: str,
    outstanding_clp: int,
    due_date: date,
) -> str:
    """The reminder while a period is past due, every few days until it is paid."""
    whose = _whose(about_name)
    return (
        f"Hola {first_name(to_name)}, {whose} de {plan_name} en {gym_name} venció el"
        f" {_fecha(due_date)} y quedan {format_clp(outstanding_clp)} por pagar."
        " ¿Nos ayudas a ponerte al día? Si ya pagaste, envíanos el comprobante. ¡Gracias!"
    )


def proof_rejected_followup(
    *,
    to_name: str,
    about_name: str | None,
    gym_name: str,
    plan_name: str,
    amount_clp: int,
    note: str,
) -> str:
    """The follow-up to a rejected proof, with the admin's note, asking for another."""
    of = "" if about_name is None else f" de {first_name(about_name)}"
    note = note.strip()
    if not note.endswith((".", "!", "?")):
        note += "."
    return (
        f"Hola {first_name(to_name)}, en {gym_name} revisamos el comprobante de"
        f" {format_clp(amount_clp)}{of} por {plan_name} y no pudimos validarlo: {note}"
        " ¿Nos envías uno nuevo? ¡Gracias!"
    )
