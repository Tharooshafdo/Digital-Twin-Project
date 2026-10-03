"""Balanced steady state. Receiving power is positive OUT of the line."""
import math
import numpy as np
import pandapower as pp
from scipy.optimize import root
from .contracts import LineConfig

MODEL_VERSION = "balanced.pi.pandapower3.5.5.v1"


def resistance(cfg, temperature_c=None):
    factor = 1.0 if temperature_c is None else (
        1 + cfg.alpha_per_c * (temperature_c - cfg.reference_temperature_c)
    )
    if factor <= 0:
        raise ValueError("Temperature relationship gives nonpositive resistance")
    return cfg.r_ohm_per_km * factor


def build_pair(cfg: LineConfig, vs_ll_kv, p_recv_mw, q_recv_mvar,
               temperature_c=None):
    net = pp.create_empty_network(sn_mva=100, f_hz=cfg.nominal_frequency_hz)
    bus_s = pp.create_bus(net, cfg.nominal_kv, name=cfg.from_bus)
    bus_r = pp.create_bus(net, cfg.nominal_kv, name=cfg.to_bus)
    pp.create_ext_grid(net, bus_s, vm_pu=vs_ll_kv / cfg.nominal_kv,
                       va_degree=0.0)
    line = pp.create_line_from_parameters(
        net, bus_s, bus_r, cfg.length_km,
        resistance(cfg, temperature_c), cfg.x_ohm_per_km,
        cfg.c_nf_per_km, cfg.max_i_ka, name=cfg.asset_id,
        g_us_per_km=cfg.g_us_per_km, parallel=cfg.parallel_circuits,
        df=cfg.derating_factor, in_service=cfg.in_service, type=cfg.line_type
    )
    # This is a boundary equivalent for the selected branch, not substation load.
    pp.create_load(net, bus_r, p_mw=p_recv_mw, q_mvar=q_recv_mvar,
                   name="receiving boundary equivalent")
    return net, bus_s, bus_r, line


def solve_line(cfg, vs_ll_kv, p_recv_mw, q_recv_mvar, temperature_c=None):
    if not cfg.in_service:
        raise ValueError("Inactive line cannot be solved as a connected branch")
    net, bs, br, line = build_pair(
        cfg, vs_ll_kv, p_recv_mw, q_recv_mvar, temperature_c
    )
    pp.runpp(net, calculate_voltage_angles=True, init="flat", numba=False,
             max_iteration=40, tolerance_mva=1e-9, lightsim2grid=False)
    r = net.res_line.loc[line]
    result = {
        "vr_ll_kv": float(net.res_bus.at[br, "vm_pu"] * cfg.nominal_kv),
        "vr_angle_deg": float(net.res_bus.at[br, "va_degree"]),
        "is_a": float(r.i_from_ka * 1000),
        "ir_a": float(r.i_to_ka * 1000),
        "p_send_mw": float(r.p_from_mw),
        "q_send_mvar": float(r.q_from_mvar),
        "p_recv_mw": float(-r.p_to_mw),
        "q_recv_mvar": float(-r.q_to_mvar),
        "loss_mw": float(r.pl_mw),
        "q_net_absorption_mvar": float(r.ql_mvar),
        "loading_percent": float(r.loading_percent),
        "r_used_ohm_per_km": resistance(cfg, temperature_c),
        "model_version": MODEL_VERSION
    }
    if any(not math.isfinite(v) for v in result.values()
           if isinstance(v, (float, int))):
        raise ValueError("Nonfinite model output")
    return result


def solve_abcd(cfg, vs_ll_kv, p_recv_mw, q_recv_mvar, temperature_c=None):
    """Independent per-phase check of the nominal pi circuit."""
    z = complex(resistance(cfg, temperature_c), cfg.x_ohm_per_km)
    z *= cfg.length_km / cfg.parallel_circuits
    y = complex(cfg.g_us_per_km * 1e-6,
                2 * np.pi * cfg.nominal_frequency_hz * cfg.c_nf_per_km * 1e-9)
    y *= cfg.length_km * cfg.parallel_circuits
    vs = vs_ll_kv * 1000 / np.sqrt(3)
    sr = complex(p_recv_mw, q_recv_mvar) * 1e6

    def equations(x):
        vr = complex(x[0], x[1])
        ir = (vs - vr) / z - y * vr / 2
        mismatch = (3 * vr * ir.conjugate() - sr) / 1e6
        return [mismatch.real, mismatch.imag]

    solved = root(equations, [vs * 0.98, -vs * 0.03])
    if not solved.success or np.linalg.norm(equations(solved.x)) > 1e-6:
        raise ValueError("Independent line calculation did not converge")
    vr = complex(*solved.x)
    ir = (vs - vr) / z - y * vr / 2
    is_ = (vs - vr) / z + y * vs / 2
    ss = 3 * vs * is_.conjugate()
    a = 1 + y * z / 2
    b = z
    c = y * (1 + y * z / 4)
    return {
        "vr_ll_kv": abs(vr) * np.sqrt(3) / 1000,
        "vr_angle_deg": float(np.angle(vr, deg=True)),
        "ir_a": abs(ir), "is_a": abs(is_),
        "p_send_mw": ss.real / 1e6, "q_send_mvar": ss.imag / 1e6,
        "loss_mw": (ss.real - sr.real) / 1e6,
        "abcd_determinant_error": abs(a * a - b * c - 1),
        "voltage_reconstruction_error_v": abs(a * vr + b * ir - vs)
    }
