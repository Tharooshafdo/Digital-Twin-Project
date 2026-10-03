"""Reviewed extension example; same interface as the real transformer plugin."""
from .domain import ShuntParameters
from .plugins import BasePlugin
class TeachingCapacitorPlugin(BasePlugin):
    type_id="example.teaching_capacitor"
    parameters=ShuntParameters
    terminal_names=("bus",)
    adapter_method="shunt"
