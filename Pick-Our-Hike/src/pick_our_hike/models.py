"""Planning inputs and internal results.

The LLM fills TripPatch with known details only. Person and Dog work for both
partial drafts and complete trips. GroupRequest checks readiness for planning;
Check and Evaluation are calculated by Python, never populated by the LLM.
"""
from datetime import date, time
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_validator, model_validator

LocalTime = Annotated[time, WithJsonSchema({"type": "string", "description": "Local clock time HH:MM (24-hour); not a timezone timestamp"})]

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

class Person(Model):
    name: str = Field(min_length=1)
    max_distance_km: float | None = Field(default=None, gt=0)
    max_ascent_m: float | None = Field(default=None, ge=0)
    distance_unlimited: bool = False
    ascent_unlimited: bool = False
    pace_minutes_per_km: float = Field(default=20, gt=0)

class Dog(Model):
    name: str = Field(min_length=1)
    max_distance_km: float | None = Field(default=None, gt=0)
    max_ascent_m: float | None = Field(default=None, ge=0)
    distance_unlimited: bool = False
    ascent_unlimited: bool = False

class TripPatch(Model):
    """Known updates only; omitted fields retain their saved values."""
    outing_date: date | None = None
    start_time: LocalTime | None = None
    latest_return_time: LocalTime | None = None
    people: list[Person] | None = None
    dogs: list[Dog] | None = None
    remove_people: list[str] = Field(default_factory=list)
    remove_dogs: list[str] = Field(default_factory=list)
    max_total_minutes: float | None = Field(default=None, gt=0)
    max_one_way_drive_minutes: float | None = Field(default=None, ge=0)
    preferred_one_way_drive_minutes: float | None = Field(default=None, ge=0)
    drive_preference_strict: bool | None = None
    parking_minutes: float | None = Field(default=None, ge=0)
    break_minutes: float | None = Field(default=None, ge=0)
    distance_unit: Literal["km", "miles"] | None = None
    elevation_unit: Literal["m", "ft"] | None = None
    clock_format: Literal["12h", "24h"] | None = None

class GroupRequest(Model):
    """Internal completeness check before calculating a plan."""
    outing_date: date
    start_time: LocalTime
    latest_return_time: LocalTime
    people: list[Person] = Field(min_length=1, max_length=5, description="A complete hiking group has 1-5 people; names are optional; unnamed people use Hiker 1, Hiker 2 labels")
    dogs: list[Dog] = Field(default_factory=list, max_length=5, description="Optional: zero to five dogs")
    max_total_minutes: float | None = Field(default=None, gt=0)
    max_one_way_drive_minutes: float | None = Field(default=None, ge=0)
    preferred_one_way_drive_minutes: float | None = Field(default=None, ge=0)
    drive_preference_strict: bool = False
    parking_minutes: float = Field(default=15, ge=0)
    break_minutes: float = Field(default=20, ge=0)
    distance_unit: Literal["km", "miles"] = "miles"
    elevation_unit: Literal["m", "ft"] = "ft"
    clock_format: Literal["12h", "24h"] = "12h"

    @field_validator("start_time", "latest_return_time")
    @classmethod
    def local_time(cls, value):
        if value.tzinfo is not None:
            raise ValueError("Use local clock times for this Redlands day trip")
        return value

    @model_validator(mode="after")
    def consistent(self):
        missing = [member.name for member in [*self.people, *self.dogs]
                   if member.max_distance_km is None and not member.distance_unlimited]
        if missing:
            raise ValueError('Please provide a hiking distance limit for: ' + ', '.join(missing))
        if self.latest_return_time <= self.start_time:
            raise ValueError("Return must be later than departure on the same day")
        for members in (self.people, self.dogs):
            names = [member.name.casefold() for member in members]
            if len(names) != len(set(names)):
                raise ValueError("Participant names must be distinct within their group")
        return self

class Check(Model):
    rule: str
    status: Literal["pass", "fail", "unknown"]
    reason: str

class Evaluation(Model):
    trail_id: str
    status: Literal["pass", "fail", "unknown"]
    checks: list[Check]
    preference_checks: list[Check] = Field(default_factory=list)
    hike_minutes_low: int
    hike_minutes_high: int
    total_minutes_high: float

