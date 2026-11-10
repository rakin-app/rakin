from datetime import date

from pydantic import BaseModel


class PrivacyNotice(BaseModel):
    """What a gym's public privacy notice fills its template in with (#168)."""

    # The gym's name, as its members know it.
    gym: str
    # The controller of the members' data: the gym, by its legal name and RUT.
    legal_name: str
    rut: str
    # Where people send requests about their data.
    email: str
    address: str | None
    # The gym's today when its details were last saved.
    updated_on: date
