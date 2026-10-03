"""Shared network adapter; no API, broker or database dependencies."""
import math
import networkx as nx
import pandapower as pp
from .domain import Network
from .plugins import registry
from tl_twin.contracts import LineConfig
from tl_twin.physics import resistance

class PandapowerAdapter:
    def __init__(self, frequency):
        self.net = pp.create_empty_network(sn_mva=100, f_hz=frequency)
        self.buses = {}
        self.elements = {}
    def remember(self, c, table, index):
        self.elements[c.id] = (table, index)
    def bus(self, c):
        i = pp.create_bus(self.net, c.parameters["nominal_kv"], name=c.id, in_service=c.in_service)
        self.buses[c.id] = i
        self.remember(c, "bus", i)
    def ends(self, c):
        return [self.buses[t.bus_id] for t in c.terminals]
    def line(self, c):
        p = registry.plugins[c.type_id].parameters.model_validate(c.parameters)
        if p.use_measured_temperature:
            raise ValueError("Connected network requires a temperature snapshot adapter; measured-temperature line supported in isolated mode only")
        a, b = self.ends(c)
        if p.sections:
            indices = []
            start = a
            for k, section in enumerate(p.sections):
                end = b if k == len(p.sections)-1 else pp.create_bus(self.net,p.nominal_kv,name=c.id+".section."+str(k),in_service=c.in_service)
                indices.append(pp.create_line_from_parameters(self.net,start,end,section.length_km,section.r_ohm_per_km,
                    section.x_ohm_per_km,section.c_nf_per_km,section.max_i_ka,g_us_per_km=section.g_us_per_km,
                    parallel=p.parallel_circuits,df=p.derating_factor,type=section.line_type,in_service=c.in_service,name=c.id+"."+section.name))
                start=end
            self.elements[c.id] = ("sections",indices)
            return
        i = pp.create_line_from_parameters(self.net, a, b, p.length_km, p.r_ohm_per_km,
            p.x_ohm_per_km, p.c_nf_per_km, p.max_i_ka, g_us_per_km=p.g_us_per_km,
            parallel=p.parallel_circuits, df=p.derating_factor, type=p.line_type,
            in_service=c.in_service, name=c.id)
        self.remember(c, "line", i)
    def transformer(self, c):
        p = registry.plugins[c.type_id].parameters.model_validate(c.parameters).model_dump(exclude={"parameter_source"})
        a, b = self.ends(c)
        i = pp.create_transformer_from_parameters(self.net, a, b, name=c.id,
            in_service=c.in_service, tap_changer_type="Ratio", **p)
        self.remember(c, "trafo", i)
    def source(self, c):
        p = c.parameters
        self.remember(c, "ext_grid", pp.create_ext_grid(self.net, self.ends(c)[0],
            vm_pu=p["vm_pu"], va_degree=p.get("va_degree", 0), name=c.id, in_service=c.in_service))
    def load(self, c):
        self.remember(c, "load", pp.create_load(self.net, self.ends(c)[0], p_mw=c.parameters["p_mw"],
            q_mvar=c.parameters["q_mvar"], name=c.id, in_service=c.in_service))
    def generator(self, c):
        self.remember(c, "sgen", pp.create_sgen(self.net, self.ends(c)[0], p_mw=c.parameters["p_mw"],
            q_mvar=c.parameters["q_mvar"], name=c.id, in_service=c.in_service))
    def shunt(self, c):
        self.remember(c, "shunt", pp.create_shunt(self.net, self.ends(c)[0], p_mw=c.parameters.get("p_mw", 0),
            q_mvar=c.parameters["q_mvar"], name=c.id, in_service=c.in_service))
    def switch(self, c):
        a, b = self.ends(c)
        self.remember(c, "switch", pp.create_switch(self.net, a, b, et="b",
            closed=c.in_service and c.parameters.get("closed", True)))
    def extract(self, c):
        if c.id not in self.elements:
            return {"status": "CATALOG_ONLY"}
        table, i = self.elements[c.id]
        if table == "switch":
            return {"status": "SIMULATED", "closed": bool(self.net.switch.at[i, "closed"])}
        if not c.in_service:
            return {"status": "DISCONNECTED"}
        if table == "sections":
            rows = self.net.res_line.loc[i]
            return {"status":"SOLVED","p_send_mw":float(rows.iloc[0].p_from_mw),"p_recv_mw":float(-rows.iloc[-1].p_to_mw),
                "loss_mw":float(rows.pl_mw.sum()),"loading_percent":float(rows.loading_percent.max()),
                "sections":[{k:float(v) for k,v in r.items() if isinstance(v,(int,float)) and math.isfinite(v)} for _,r in rows.iterrows()]}
        row = getattr(self.net, "res_" + table).loc[i]
        result = {k: float(v) for k, v in row.items() if isinstance(v, (int, float)) and math.isfinite(v)}
        if table == "bus":
            result["voltage_kv"] = result["vm_pu"] * c.parameters["nominal_kv"]
        if table == "line":
            result.update(p_send_mw=result["p_from_mw"], p_recv_mw=-result["p_to_mw"],
                          loss_mw=result["pl_mw"])
        return {"status": "SOLVED", **result}

def solve_network(payload, snapshot_id):
    network = registry.validate(Network.model_validate(payload), study=True)
    import pandapower.topology as topology
    adapter = PandapowerAdapter(network.frequency_hz)
    for c in sorted(network.components, key=lambda c: c.type_id != "ac.bus"):
        p = registry.plugins[c.type_id]
        if p.capabilities.get("study"):
            p.contribute(adapter, p.update_snapshot(c, {}))
    net = adapter.net
    graph = topology.create_nxgraph(net)
    for island in nx.connected_components(graph):
        sources = net.ext_grid[(net.ext_grid.bus.isin(island)) & net.ext_grid.in_service]
        if len(sources) != 1:
            raise ValueError(f"Each supplied island requires exactly one external reference; found {len(sources)}")
    if len(topology.unsupplied_buses(net)):
        raise ValueError("Unsupplied island")
    pp.runpp(net, numba=False, calculate_voltage_angles=True, tolerance_mva=1e-9,
             lightsim2grid=False, max_iteration=40)
    if not net.converged:
        raise ValueError("Power flow failed to converge")
    source = float(net.res_ext_grid.p_mw.sum() + net.res_sgen.p_mw.sum())
    demand = float(net.res_load.p_mw.sum() + net.res_shunt.p_mw.sum())
    losses = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
    return {"snapshot_id": snapshot_id, "model_status": "SOLVED", "mode": "connected_network",
            "source_mw": source, "demand_mw": demand, "loss_mw": losses,
            "active_power_balance_error_mw": source - demand - losses,
            "components": {c.id: {"snapshot_id": snapshot_id, **registry.plugins[c.type_id].extract(adapter, c)}
                           for c in network.components},
            "policy": "One external grid per supplied island; fixed PQ generation; no PV/Q-limit controls"}

def line_config(component, revision_id, valid_from="2020-01-01T00:00:00Z", valid_to=None):
    c = component
    p = registry.plugins["ac.line"].parameters.model_validate(c["parameters"]).model_dump(exclude={"sections", "rating_source"})
    return LineConfig(asset_id=c["id"], parameter_version=c.get("parameter_version", revision_id),
        topology_version=revision_id, valid_from=valid_from, valid_to=valid_to,
        from_bus=c["terminals"][0]["bus_id"], to_bus=c["terminals"][1]["bus_id"],
        in_service=c.get("in_service", True), **p)
