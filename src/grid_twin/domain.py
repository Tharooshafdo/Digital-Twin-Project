"""Transport-independent component contracts and controlled plugin registry."""
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator
from packaging.specifiers import SpecifierSet
from packaging.version import Version

PLATFORM_VERSION = "0.1.0"

class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class BusParameters(Parameters):
    nominal_kv: float = Field(gt=0, json_schema_extra={"unit": "kV"})
    domain: Literal["AC"] = "AC"
    phases: Literal["positive_sequence"] = "positive_sequence"

class ElectricalSection(Parameters):
    name: str = Field(min_length=1)
    line_type: Literal["ol", "cs"]
    length_km: float = Field(gt=0)
    r_ohm_per_km: float = Field(ge=0)
    x_ohm_per_km: float = Field(gt=0)
    c_nf_per_km: float = Field(ge=0)
    g_us_per_km: float = Field(default=0, ge=0)
    max_i_ka: float = Field(gt=0)
    parameter_source: str = Field(min_length=1)
    rating_source: str = Field(min_length=1)

class LineParameters(Parameters):
    nominal_kv: float = Field(gt=0, json_schema_extra={"unit": "kV"})
    length_km: float = Field(gt=0, json_schema_extra={"unit": "km"})
    r_ohm_per_km: float = Field(ge=0, json_schema_extra={"unit": "ohm/km"})
    x_ohm_per_km: float = Field(gt=0, json_schema_extra={"unit": "ohm/km"})
    c_nf_per_km: float = Field(ge=0, json_schema_extra={"unit": "nF/km"})
    g_us_per_km: float = Field(default=0, ge=0, json_schema_extra={"unit": "uS/km"})
    nominal_frequency_hz: float = Field(default=50, gt=0)
    max_i_ka: float = Field(gt=0, json_schema_extra={"unit": "kA per full circuit"})
    parallel_circuits: int = Field(default=1, ge=1)
    bundle_count_per_phase: int = Field(default=1, ge=1)
    derating_factor: float = Field(default=1, gt=0, le=1)
    line_type: Literal["ol", "cs"] = "ol"
    reference_temperature_c: float = 20
    alpha_per_c: float = Field(default=0.00403, ge=0)
    use_measured_temperature: bool = False
    parameter_source: str = Field(min_length=1)
    rating_source: str = "Illustrative; requires approved circuit rating"
    voltage_warn_kv: float | None = Field(default=0.4, gt=0)
    voltage_alarm_kv: float | None = Field(default=0.8, gt=0)
    sections: list[ElectricalSection] = Field(default_factory=list)

    @model_validator(mode="after")
    def boundaries(self):
        if self.voltage_warn_kv and self.voltage_alarm_kv and self.voltage_alarm_kv <= self.voltage_warn_kv:
            raise ValueError("Alarm threshold must exceed warning threshold")
        if self.sections and abs(sum(s.length_km for s in self.sections)-self.length_km) > 1e-6:
            raise ValueError("Section lengths must sum to line length")
        if len({s.name for s in self.sections}) != len(self.sections):
            raise ValueError("Section names must be unique")
        return self

class TransformerParameters(Parameters):
    sn_mva: float = Field(gt=0)
    vn_hv_kv: float = Field(gt=0)
    vn_lv_kv: float = Field(gt=0)
    vk_percent: float = Field(gt=0)
    vkr_percent: float = Field(ge=0)
    pfe_kw: float = Field(ge=0)
    i0_percent: float = Field(ge=0)
    shift_degree: float = 0
    tap_side: Literal["hv", "lv"] = "hv"
    tap_neutral: int = 0
    tap_min: int = -8
    tap_max: int = 8
    tap_pos: int = 0
    tap_step_percent: float = Field(default=1.25, ge=0)
    parameter_source: str = "Synthetic teaching transformer"

    @model_validator(mode="after")
    def bounds(self):
        if not self.tap_min <= self.tap_pos <= self.tap_max or self.vkr_percent > self.vk_percent:
            raise ValueError("Invalid tap range or transformer impedance")
        if self.vn_hv_kv <= self.vn_lv_kv:
            raise ValueError("HV rated voltage must exceed LV rated voltage")
        return self

class PQParameters(Parameters):
    p_mw: float
    q_mvar: float
    parameter_source: str = "Synthetic PQ injection"

class SourceParameters(Parameters):
    vm_pu: float = Field(default=1.01, gt=0, le=1.5)
    va_degree: float = 0
    parameter_source: str = "Synthetic external reference"

class ShuntParameters(Parameters):
    q_mvar: float
    p_mw: float = Field(default=0, ge=0)
    parameter_source: str = "Synthetic fixed shunt"

class SwitchParameters(Parameters):
    closed: bool = True

class MetadataParameters(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    parameter_source: str = "Unverified catalog metadata"

class Terminal(Parameters):
    name: str
    bus_id: str
    domain: Literal["AC", "DC"] = "AC"
    nominal_kv: float = Field(gt=0)
    phases: Literal["positive_sequence", "abc", "dc"] = "positive_sequence"

class Component(Parameters):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$", max_length=80)
    type_id: str
    name: str
    parameters: dict
    terminals: list[Terminal] = Field(default_factory=list)
    in_service: bool = True
    parent_id: str | None = None
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})
    parameter_version: str = "draft"

class Network(Parameters):
    frequency_hz: float = Field(default=50, gt=0)
    components: list[Component]
    provenance: str = "synthetic"

class Plugin(Protocol):
    type_id: str
    version: str
    platform: str
    parameters: type[BaseModel]
    terminal_names: tuple[str, ...]
    capabilities: dict
    def contribute(self, adapter, component: Component): ...
    def extract(self, adapter, component: Component): ...

class Registry:
    def __init__(self):
        self.plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin):
        if Version(PLATFORM_VERSION) not in SpecifierSet(plugin.platform):
            raise ValueError("Plugin incompatible with platform")
        if plugin.type_id in self.plugins:
            raise ValueError("Duplicate plugin type")
        self.plugins[plugin.type_id] = plugin

    def catalog(self):
        return [{"type_id": p.type_id, "plugin_version": p.version,
                 "compatible_platform": p.platform, "capabilities": p.capabilities,
                 "parameter_schema": p.parameters.model_json_schema(),
                 "terminal_names": p.terminal_names, "symbol": p.type_id.split('.')[-1],
                 "measurement_channels": LINE_CHANNELS if p.type_id == "ac.line" else [],
                 "optional_hooks": [], "result_fields": p.capabilities.get("results", [])}
                for p in self.plugins.values()]

    def validate(self, network: Network, study=False):
        ids = [c.id for c in network.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate component IDs")
        buses = {c.id: c for c in network.components if c.type_id == "ac.bus"}
        for c in network.components:
            p = self.plugins.get(c.type_id)
            if p is None:
                raise ValueError(f"Uninstalled plugin: {c.type_id}")
            params = p.parameters.model_validate(c.parameters)
            if study and c.in_service and not p.capabilities.get("study"):
                raise ValueError(f"Unsupported in-service component {c.id}: {c.type_id}")
            if c.parent_id and (c.parent_id not in ids or c.parent_id == c.id):
                raise ValueError("Invalid organizational parent")
            if tuple(t.name for t in c.terminals) != p.terminal_names:
                raise ValueError(f"{c.id} requires terminals {p.terminal_names}")
            for t in c.terminals:
                if t.bus_id not in buses:
                    raise ValueError(f"Missing shared bus {t.bus_id}")
                b = BusParameters.model_validate(buses[t.bus_id].parameters)
                if t.domain != b.domain or t.phases != b.phases or abs(t.nominal_kv-b.nominal_kv) > 1e-6:
                    raise ValueError("Terminal domain/phase/voltage incompatible with bus")
            if len(c.terminals) == 2 and c.terminals[0].bus_id == c.terminals[1].bus_id:
                raise ValueError("Two terminals must use distinct buses")
            if c.type_id in ("ac.line", "ac.switch") and len(c.terminals) == 2:
                if c.terminals[0].nominal_kv != c.terminals[1].nominal_kv:
                    raise ValueError("Voltage transition requires transformer")
            if c.type_id == "ac.line" and c.terminals[0].nominal_kv != params.nominal_kv:
                raise ValueError("Line nominal voltage disagrees with terminal")
            if c.type_id == "ac.line" and params.nominal_frequency_hz != network.frequency_hz:
                raise ValueError("Line frequency disagrees with shared network")
            if c.type_id == "ac.transformer2w":
                if [t.nominal_kv for t in c.terminals] != [params.vn_hv_kv, params.vn_lv_kv]:
                    raise ValueError("Transformer rated and terminal voltages disagree")
        return network

LINE_CHANNELS = [{"name": k, "unit": u, "role": r, "quality": ["GOOD", "BAD", "SUSPECT", "MISSING"]}
    for k, u, r in [("vs_ll_kv", "kV", "input"), ("p_recv_mw", "MW", "input"),
                    ("q_recv_mvar", "MVAr", "input"), ("vr_ll_kv", "kV", "validation"),
                    ("p_send_mw", "MW", "validation"), ("q_send_mvar", "MVAr", "validation"),
                    ("is_a", "A", "validation"), ("ir_a", "A", "validation"),
                    ("conductor_temp_c", "C", "optional input")]]
