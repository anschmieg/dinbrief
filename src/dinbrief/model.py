from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Address(StrictModel):
    street: str
    postal_code: str
    city: str
    region: str | None = None
    country: str = Field(default="DE", pattern=r"^[A-Z]{2}$")
    extra: list[str] = Field(default_factory=list)


class Party(StrictModel):
    name: str | None = None
    organization: str | None = None
    department: str | None = None
    address: Address
    phone: str | None = None
    email: str | None = None
    website: str | None = None

    @field_validator("name", "organization", "department", mode="before")
    @classmethod
    def empty_string_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.organization:
            return self.organization
        raise ValueError("A party needs either name or organization")


class Layout(StrictModel):
    standard: Literal["din-5008"] = "din-5008"
    form: Literal["A", "B"] = "B"
    window_envelope: bool = True
    fold_marks: bool = True
    hole_mark: bool = True


class Delivery(StrictModel):
    method: Literal["print", "email", "both"] = "both"


class Letter(StrictModel):
    format: Literal["dinbrief/v2"] = "dinbrief/v2"
    language: str = Field(default="de-DE", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    sender: str | Party
    recipient: Party
    date: date
    location: str | None = None
    subject: str = Field(min_length=1, exclude=True)
    salutation: str = Field(min_length=1)
    closing: str = Field(min_length=1)
    references: dict[str, str] = Field(default_factory=dict)
    delivery: Delivery = Field(default_factory=Delivery)
    layout: Layout = Field(default_factory=Layout)
    tags: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip().lower() for tag in tags if tag.strip()))

    @field_validator("sender", "recipient")
    @classmethod
    def party_needs_identity(cls, value: str | Party) -> str | Party:
        if isinstance(value, Party) and not (value.name or value.organization):
            raise ValueError("Provide at least name or organization")
        return value


class ParsedLetter(BaseModel):
    source: str
    metadata: Letter
    body: str
    raw_metadata: dict[str, Any]
