"""The role a `staff` row still names: owner, admin or coach.

What a person may do is read from their permissions (`app.permissions`) since #308.
The column stays, written by the staff API alongside each appointment, though nothing
in the database reads it since #309; #313 drops it, and this with it.
"""

from enum import StrEnum

from app.permissions import ADMINISTRADOR, COACH


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    COACH = "coach"


# The Academia preset's role each of today's staff roles is appointed to; the owner is
# the titular instead (`staff.account_holder`), and holds every permission by the flag.
TITLE_OF = {Role.ADMIN: ADMINISTRADOR, Role.COACH: COACH}
