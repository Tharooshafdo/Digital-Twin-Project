"""Reviewed built-ins. New classes register without changing solver dispatch."""
from .domain import (Registry, BusParameters, LineParameters, TransformerParameters,
                     SourceParameters, PQParameters, ShuntParameters, SwitchParameters, MetadataParameters)

class BasePlugin:
    version = "1.0.0"
    platform = ">=0.1,<0.2"
    capabilities = {"catalog": True, "study": True, "twin": False, "studies": ["balanced_ac"]}
    terminal_names = ()
    def contribute(self, adapter, component):
        return getattr(adapter, self.adapter_method)(component)
    def extract(self, adapter, component):
        return adapter.extract(component)
    def validate_component(self, component):
        return self.parameters.model_validate(component.parameters)
    def update_snapshot(self, component, snapshot_inputs):
        """Pure hook for a reviewed plugin to derive its snapshot parameters."""
        return component
    def optional_analytics(self, state):
        return {}

class BusPlugin(BasePlugin):
    type_id = "ac.bus"
    parameters = BusParameters
    adapter_method = "bus"

class LinePlugin(BasePlugin):
    type_id = "ac.line"
    parameters = LineParameters
    terminal_names = ("from", "to")
    adapter_method = "line"
    capabilities = {"catalog": True, "study": True, "twin": True,
                    "studies": ["balanced_ac", "isolated_pi"],
                    "results": ["voltage_kv", "p_send_mw", "loss_mw", "loading_percent"],
                    "boundary": "Balanced synthetic/offline twin; field validation unavailable"}

class TransformerPlugin(BasePlugin):
    type_id = "ac.transformer2w"
    parameters = TransformerParameters
    terminal_names = ("hv", "lv")
    adapter_method = "transformer"

class SourcePlugin(BasePlugin):
    type_id = "ac.external_grid"
    parameters = SourceParameters
    terminal_names = ("bus",)
    adapter_method = "source"

class LoadPlugin(BasePlugin):
    type_id = "ac.load_pq"
    parameters = PQParameters
    terminal_names = ("bus",)
    adapter_method = "load"

class GeneratorPlugin(LoadPlugin):
    type_id = "ac.generator_pq"
    adapter_method = "generator"

class ShuntPlugin(BasePlugin):
    type_id = "ac.shunt"
    parameters = ShuntParameters
    terminal_names = ("bus",)
    adapter_method = "shunt"

class SwitchPlugin(BasePlugin):
    type_id = "ac.switch"
    parameters = SwitchParameters
    terminal_names = ("from", "to")
    adapter_method = "switch"

class CatalogPlugin(BasePlugin):
    parameters = MetadataParameters
    capabilities = {"catalog": True, "study": False, "twin": False, "studies": []}
    def __init__(self, type_id):
        self.type_id = type_id

def builtins():
    registry = Registry()
    for cls in (BusPlugin, LinePlugin, TransformerPlugin, SourcePlugin, LoadPlugin,
                GeneratorPlugin, ShuntPlugin, SwitchPlugin):
        registry.register(cls())
    for name in ("substation", "feeder", "transformer3w", "motor", "load_zip", "battery",
                 "pv", "wind", "hydro", "diesel", "synchronous_machine", "svc", "statcom", "hvdc",
                 "converter", "reactor", "meter", "ct_pt", "pmu", "ied", "relay", "weather_sensor",
                 "tower", "span", "conductor", "insulator", "earthing", "arrester"):
        registry.register(CatalogPlugin("catalog." + name))
    return registry

registry = builtins()

def enable_reviewed_plugins(approved_entrypoints=()):
    """Explicit allowlist of installed distribution entry points, configured by developer."""
    from importlib.metadata import entry_points
    candidates={p.name:p for p in entry_points(group="grid_twin.components")}
    for name in approved_entrypoints:
        if name not in candidates:
            raise ValueError(f"Approved installed plugin entrypoint missing: {name}")
        registry.register(candidates[name].load()())
