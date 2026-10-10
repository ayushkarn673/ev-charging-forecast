"""Request/response models for the prediction API. JSON uses camelCase (for the Spring Boot client)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------- request
class NextHourRequest(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    site_id: str = Field(default="caltech", description="Charging site. Only 'caltech' is available.")
    forecast_time: datetime = Field(
        description="Simulated 'now' (ISO 8601 with offset, on the hour). The forecast is for the hour "
                    "[forecastTime, forecastTime + 1 h).",
        examples=["2020-01-15T08:00:00-08:00"])

    @field_validator("forecast_time")
    @classmethod
    def _aware_and_on_the_hour(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("forecastTime must include a timezone offset, e.g. 2020-01-15T08:00:00-08:00")
        if v.minute or v.second or v.microsecond:
            raise ValueError("forecastTime must be on an hour boundary (minutes and seconds = 0)")
        return v


# ---------------------------------------------------------------- response pieces
class Prediction(CamelModel):
    utilization: float = Field(description="Predicted utilization ratio, clipped to [0, 1].")
    utilization_percent: float
    estimated_occupied_spaces: float = Field(description="Time-weighted average over the hour (estimate, fractional).")
    estimated_occupied_spaces_rounded: int = Field(description="ceil(estimatedOccupiedSpaces).")
    estimated_available_spaces_rounded: int = Field(description="capacity - estimatedOccupiedSpacesRounded.")
    raw_utilization: float = Field(description="Unclipped model output, for diagnostics.")


class ObservedOutcome(CamelModel):
    utilization: float
    utilization_percent: float
    average_occupied_spaces: float
    note: str


class InputWindow(CamelModel):
    first_input_hour: str
    last_input_hour: str
    earliest_observation_used: str
    latest_observation_used: str
    sequence_length: int
    features: list[str]


class Warning_(CamelModel):
    code: str
    message: str


class NextHourResponse(CamelModel):
    mode: str
    is_simulation: bool
    notice: str
    site_id: str
    installed_capacity_spaces: int
    forecast_time: str
    forecast_time_utc: str
    target_start: str
    target_end: str
    horizon_hours: int
    inputs: InputWindow
    prediction: Prediction
    rounding_policy: str
    observed_outcome: ObservedOutcome | None
    model_id: str
    warnings: list[Warning_]


class HealthResponse(CamelModel):
    status: str
    model_loaded: bool
    model_id: str | None
    observations_loaded: int
    loaded_at_utc: str | None


class ErrorResponse(CamelModel):
    code: str
    message: str
