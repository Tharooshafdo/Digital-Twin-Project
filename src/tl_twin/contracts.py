from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Quality = Literal["GOOD", "SUSPECT", "BAD", "MISSING"]
INPUTS = ("vs_ll_kv", "p_recv_mw", "q_recv_mvar")
OUTPUTS = ("vr_ll_kv", "ir_a", "is_a", "p_send_mw", "q_send_mvar")


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An explicit UTC offset or timezone is required")
    return value.astimezone(timezone.utc)


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["line.measurement.v1"] = "line.measurement.v1"
    message_id: str = Field(min_length=1, max_length=128)
    asset_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    event_time: datetime
    source_id: str = Field(min_length=1, max_length=128)
    dataset_id: str = Field(min_length=1, max_length=128)
    data_origin: Literal["synthetic", "utility", "laboratory"]
    sequence_no: int = Field(ge=0)
    connection_state: Literal[
        "CONNECTED", "RECEIVING_OPEN", "DEENERGIZED", "UNKNOWN"
    ] = "UNKNOWN"
    vs_ll_kv: float | None = Field(default=None, ge=0)
    vr_ll_kv: float | None = Field(default=None, ge=0)
    is_a: float | None = Field(default=None, ge=0)
    ir_a: float | None = Field(default=None, ge=0)
    p_send_mw: float | None = None
    q_send_mvar: float | None = None
    p_recv_mw: float | None = None
    q_recv_mvar: float | None = None
    frequency_hz: float | None = Field(default=None, gt=0)
    conductor_temp_c: float | None = None
    signal_quality: dict[str, Quality] = Field(default_factory=dict)
    uncertainty: dict[str, float] = Field(default_factory=dict)
    original_timestamp: str | None = None
    source_metadata: dict = Field(default_factory=dict)

    @field_validator("event_time")
    @classmethod
    def normalize_time(cls, value):
        return utc(value)

    @field_validator("uncertainty")
    @classmethod
    def positive_sigmas(cls, values):
        import math
        if any(not math.isfinite(v) or v <= 0 for v in values.values()):
            raise ValueError("Measurement standard deviations must be positive")
        return values

    def usable(self, key: str) -> bool:
        return (getattr(self, key, None) is not None
                and self.signal_quality.get(key, "GOOD") == "GOOD")


class LineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    asset_id: str
    parameter_version: str
    topology_version: str
    valid_from: datetime
    valid_to: datetime | None = None
    from_bus: str
    to_bus: str
    nominal_kv: float = Field(gt=0)
    nominal_frequency_hz: float = Field(default=50.0, gt=0)
    length_km: float = Field(gt=0)
    r_ohm_per_km: float = Field(ge=0)
    x_ohm_per_km: float = Field(gt=0)
    c_nf_per_km: float = Field(ge=0)
    g_us_per_km: float = Field(default=0.0, ge=0)
    max_i_ka: float = Field(gt=0)
    parallel_circuits: int = Field(default=1, ge=1)
    bundle_count_per_phase: int = Field(default=1, ge=1)
    derating_factor: float = Field(default=1.0, gt=0, le=1)
    line_type: Literal["ol", "cs"] = "ol"
    in_service: bool = True
    reference_temperature_c: float = 20.0
    alpha_per_c: float = Field(default=0.00403, ge=0)
    use_measured_temperature: bool = False
    parameter_source: str
    voltage_warn_kv: float | None = Field(default=None, gt=0)
    voltage_alarm_kv: float | None = Field(default=None, gt=0)

    @field_validator("valid_from", "valid_to")
    @classmethod
    def normalize_time(cls, value):
        return utc(value) if value is not None else value


def load_configs(path: str) -> list[LineConfig]:
    import json
    with open(path, encoding="utf-8") as handle:
        configs = [LineConfig.model_validate(x) for x in json.load(handle)]
    for cfg in configs:
        if cfg.from_bus == cfg.to_bus:
            raise ValueError("Line terminals must refer to different buses")
        if cfg.valid_to is not None and cfg.valid_to <= cfg.valid_from:
            raise ValueError("Invalid parameter validity interval")
        if (cfg.voltage_warn_kv and cfg.voltage_alarm_kv
                and cfg.voltage_alarm_kv <= cfg.voltage_warn_kv):
            raise ValueError("Alarm limit must exceed warning limit")
    return configs


def parameter_for(configs, asset_id, when):
    candidates = [c for c in configs if c.asset_id == asset_id
                  and c.valid_from <= when
                  and (c.valid_to is None or when < c.valid_to)]
    if len(candidates) != 1:
        raise ValueError("Exactly one parameter version must cover event time")
    return candidates[0]
