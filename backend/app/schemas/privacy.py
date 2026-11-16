from datetime import date

from pydantic import BaseModel

from app.domain.vocabulary import DEFAULT, Vocabulary

# The day the notice's text last changed: the SPA's `TEMPLATE_UPDATED_ON`
# (`frontend/src/api/privacy.ts`), which keeps the text, and a test holds the two
# equal. What someone accepts names it (#370), so a form showing an older text is
# refused.
TEMPLATE_UPDATED_ON = date(2026, 11, 15)


class PrivacyNotice(BaseModel):
    """What a gym's public privacy notice fills its template in with (#168)."""

    # The gym's name, as its members know it.
    gym: str
    # Where the gym's logo's files are (`app.logos.logo_path`); None with no logo (#223).
    gym_logo: str | None = None
    # The controller of the members' data: the gym, by its legal name and RUT.
    legal_name: str
    rut: str
    # Where people send requests about their data.
    email: str
    address: str | None
    # The gym's today when its details were last saved.
    updated_on: date
    # Whether the join form checks for humans (`HUMAN_CHECK`), so the notice names that
    # provider only where it is used.
    human_check: bool
    # What the gym calls itself and its members (#344): the notice's words.
    vocabulary: Vocabulary = DEFAULT
