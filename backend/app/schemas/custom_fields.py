"""Custom-field definitions and a person's values, as the API takes and answers them.

The rules of a value live in `app.domain.custom_fields`; these are the shapes.
"""

from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

from app.domain.custom_fields import FieldType, VisibleTo

Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Option = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


def _distinct(options: list[str]) -> list[str]:
    if len(set(options)) != len(options):
        raise ValueError("options must be distinct")
    return options


Options = Annotated[list[Option], Field(min_length=1, max_length=50), AfterValidator(_distinct)]


class FieldDefinition(BaseModel):
    key: str
    label: str
    type: FieldType
    # An enum's choices, in order; `None` on every other type.
    options: list[str] | None = None
    sensitive: bool
    visible_to: VisibleTo
    archived: bool


class FieldCreate(BaseModel):
    """A new field. Its key is made from the label. `sensitive` and `visible_to` are
    the owner's to set; without them the field is not sensitive, and seen by every
    staff role, or by the owner alone when sensitive."""

    model_config = ConfigDict(extra="forbid")

    label: Label
    type: FieldType
    options: Options | None = None
    sensitive: StrictBool = False
    visible_to: VisibleTo | None = None

    @model_validator(mode="after")
    def _options_only_on_enums(self) -> "FieldCreate":
        if (self.type is FieldType.ENUM) != (self.options is not None):
            raise ValueError("options are required on an enum field, and only there")
        return self


class FieldUpdate(BaseModel):
    """Only the fields sent change; none can be cleared. The type and key are fixed.
    Marking a field sensitive without a `visible_to` narrows it to the owner."""

    model_config = ConfigDict(extra="forbid")

    label: Label | None = None
    options: Options | None = None
    archived: StrictBool | None = None
    sensitive: StrictBool | None = None
    visible_to: VisibleTo | None = None

    @model_validator(mode="after")
    def _nothing_is_cleared(self) -> "FieldUpdate":
        cleared = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if cleared:
            raise ValueError(f"{', '.join(cleared)} cannot be null")
        return self


class FieldOrder(BaseModel):
    """Every field the caller sees, by key, in the order they should be shown."""

    model_config = ConfigDict(extra="forbid")

    keys: list[str]


class PersonField(BaseModel):
    """One field on a person's detail, with what the gym recorded; `value` is `None`
    when nothing is."""

    key: str
    label: str
    type: FieldType
    options: list[str] | None = None
    sensitive: bool
    value: Any


class PersonFieldsUpdate(BaseModel):
    """Values by field key; `null` clears one. Fields not sent keep their values."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any]
