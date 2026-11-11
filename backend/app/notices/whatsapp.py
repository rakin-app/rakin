"""The WhatsApp messages Rakin writes for the admin to send, in Spanish.

v1 sends none itself: each is prefilled in a `wa.me` link (`app.integrations.messenger`)
that the admin opens from one of their lists, and recorded in `message_log` as they
open it (migration 0024). Each template has a name, the row's `template`.

They are short and plain text, as a WhatsApp message is, and greet by first name.
"""

INACTIVE_NUDGE = "inactive_nudge"
EXTRA_CHARGE_REMINDER = "extra_charge_reminder"


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


def extra_charge_reminder(
    *, to_name: str, about_name: str | None, gym_name: str, title: str, amount: str, due: str
) -> str:
    """A cobro extra's notice on WhatsApp (#195), for someone with no email to get it
    by, or as a reminder; to their guardian (`about_name`) for a dependent. `amount` and
    `due` come formatted."""
    whose = f" de {first_name(about_name)}" if about_name else ""
    return (
        f"Hola {first_name(to_name)}, te escribimos de {gym_name} por el cobro {title}{whose}:"
        f" {amount}, hasta el {due}. Puedes transferir y subir el comprobante en tu página."
        " ¡Gracias!"
    )
