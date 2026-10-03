"""One shared solver for electrically connected component models."""
import json
from pathlib import Path
import numpy as np
import pandapower as pp
import pandapower.topology as topology


def build_network(spec):
    net = pp.create_empty_network(sn_mva=100, f_hz=spec["frequency_hz"])
    buses = {}
    for b in spec["buses"]:
        if b["id"] in buses:
            raise ValueError("Duplicate shared bus ID")
        buses[b["id"]] = pp.create_bus(net, b["nominal_kv"], name=b["id"])
    for source in spec["sources"]:
        pp.create_ext_grid(net, buses[source["bus"]], vm_pu=source["vm_pu"],
                           va_degree=source.get("va_degree", 0),
                           s_sc_max_mva=source.get("s_sc_max_mva", 3000),
                           rx_max=source.get("rx_max", 0.1))
    for line in spec["lines"]:
        a, b = buses[line["from_bus"]], buses[line["to_bus"]]
        if net.bus.at[a, "vn_kv"] != net.bus.at[b, "vn_kv"]:
            raise ValueError("Voltage-level transition requires a transformer")
        pp.create_line_from_parameters(net, a, b, line["length_km"],
            line["r_ohm_per_km"], line["x_ohm_per_km"], line["c_nf_per_km"],
            line["max_i_ka"], name=line["id"],
            in_service=line.get("in_service", True),
            parallel=line.get("parallel_circuits", 1))
    for trafo in spec.get("transformers", []):
        args = {k: v for k, v in trafo.items() if k not in ("id", "hv_bus", "lv_bus")}
        pp.create_transformer_from_parameters(net, buses[trafo["hv_bus"]],
            buses[trafo["lv_bus"]], name=trafo["id"], **args)
    for load in spec.get("loads", []):
        pp.create_load(net, buses[load["bus"]], p_mw=load["p_mw"],
                       q_mvar=load["q_mvar"], name=load["id"])
    for gen in spec.get("generators", []):
        pp.create_sgen(net, buses[gen["bus"]], p_mw=gen["p_mw"],
                       q_mvar=gen["q_mvar"], name=gen["id"])
    if len(topology.unsupplied_buses(net)):
        raise ValueError("Unsupplied island; no valid shared-network snapshot")
    return net, buses


def solve_network(spec):
    net, buses = build_network(spec)
    pp.runpp(net, numba=False, calculate_voltage_angles=True, tolerance_mva=1e-9,
             lightsim2grid=False)
    if not np.isfinite(net.res_bus.vm_pu).all():
        raise ValueError("Nonfinite shared bus voltages")
    losses = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    supply = net.res_ext_grid.p_mw.sum() + net.res_sgen.p_mw.sum()
    demand = net.res_load.p_mw.sum()
    return {"snapshot_id": spec["snapshot_id"], "event_time": spec["event_time"],
        "topology_version": spec["topology_version"],
        "buses": {name: {"voltage_kv": float(net.res_bus.at[i, "vm_pu"] *
            net.bus.at[i, "vn_kv"]), "angle_deg": float(net.res_bus.at[i, "va_degree"])}
            for name, i in buses.items()},
        "lines": {net.line.at[i, "name"]: {
            "p_send_mw": float(r.p_from_mw), "p_recv_mw": float(-r.p_to_mw),
            "loss_mw": float(r.pl_mw), "loading_percent": float(r.loading_percent)}
            for i, r in net.res_line.iterrows()},
        "total_loss_mw": float(losses),
        "active_power_balance_error_mw": float(supply - demand - losses)}


def load_network(path="config/network.json"):
    return json.loads(Path(path).read_text(encoding="utf-8"))
