"""Executable teaching experiments. Every parameter here is synthetic."""
import numpy as np
import pandapower as pp
from pandapower.estimation import estimate
from pandapower.shortcircuit import calc_sc
from scipy.optimize import brentq
from scipy.integrate import solve_ivp
from .network import build_network, load_network, solve_network
from .contracts import load_configs
from .physics import build_pair, resistance


def network_demo():
    return solve_network(load_network())


def estimate_demo():
    spec = load_network()
    # Use three buses to keep the placement and state vector easy to inspect.
    spec["buses"] = spec["buses"][:3]
    spec["transformers"] = []
    spec["loads"] = spec["loads"][:2]
    net, buses = build_network(spec)
    pp.runpp(net, numba=False, calculate_voltage_angles=True, lightsim2grid=False)
    truth = net.res_bus.vm_pu.copy()
    for i in net.bus.index:
        pp.create_measurement(net, "v", "bus", truth.at[i], 0.002, i)
    for i in net.line.index:
        for kind, column, sigma in (("p", "p_from_mw", 0.1),
                                    ("q", "q_from_mvar", 0.1)):
            pp.create_measurement(net, kind, "line", net.res_line.at[i, column],
                                   sigma, i, side="from")
    result = estimate(net, init="flat", tolerance=1e-8, maximum_iterations=30)
    success = bool(result.get("success", False)) if isinstance(result, dict) else bool(result)
    if not success:
        raise ValueError("State estimator did not converge")
    return {"data_origin": "synthetic", "success": success,
        "measurements": len(net.measurement), "unknown_states": 2 * len(net.bus) - 1,
        "max_voltage_error_pu": float(np.abs(net.res_bus_est.vm_pu - truth).max()),
        "estimated_bus_voltage_pu": net.res_bus_est.vm_pu.to_dict()}


def three_phase_demo():
    net = pp.create_empty_network(f_hz=50, sn_mva=10)
    a = pp.create_bus(net, 20, name="MV_A")
    b = pp.create_bus(net, 20, name="MV_B")
    pp.create_ext_grid(net, a, vm_pu=1.02, s_sc_max_mva=1000,
        s_sc_min_mva=800, rx_max=0.1, rx_min=0.1, r0x0_max=0.1, x0x_max=1.0)
    pp.create_line_from_parameters(net, a, b, length_km=2,
        r_ohm_per_km=0.2, x_ohm_per_km=0.3, c_nf_per_km=10, max_i_ka=0.4,
        r0_ohm_per_km=0.6, x0_ohm_per_km=0.9, c0_nf_per_km=5)
    pp.create_asymmetric_load(net, b, p_a_mw=0.3, p_b_mw=0.2, p_c_mw=0.1,
                              q_a_mvar=0.08, q_b_mvar=0.05, q_c_mvar=0.02, type="wye")
    pp.runpp_3ph(net, numba=False, max_iteration=40, tolerance_mva=1e-9)
    row = net.res_bus_3ph.loc[b]
    phase = np.array([row[f"vm_{s}_pu"] * np.exp(
        1j * np.deg2rad(row[f"va_{s}_degree"])) for s in "abc"])
    alpha = np.exp(2j * np.pi / 3)
    zero = (phase[0] + phase[1] + phase[2]) / 3
    positive = (phase[0] + alpha * phase[1] + alpha**2 * phase[2]) / 3
    negative = (phase[0] + alpha**2 * phase[1] + alpha * phase[2]) / 3
    return {"data_origin": "synthetic", "phase_voltage_pu": np.abs(phase).tolist(),
        "zero_sequence_pu": float(abs(zero)),
        "positive_sequence_pu": float(abs(positive)),
        "negative_sequence_pu": float(abs(negative)),
        "voltage_unbalance_percent": float(100 * abs(negative) / abs(positive))}


def fault_demo():
    net, buses = build_network(load_network())
    calc_sc(net, fault="3ph", case="max", bus=buses["BUS_C"],
            ip=True, ith=True, tk_s=1.0)
    r = net.res_bus_sc.loc[buses["BUS_C"]]
    return {"data_origin": "synthetic", "fault_type": "IEC 60909 three phase",
        "ikss_ka": float(r.ikss_ka), "ip_ka": float(r.ip_ka),
        "ith_ka": float(r.ith_ka), "waveforms_computed": False}


def heat_terms(t, current_a, ambient_c=35, wind_m_s=0.6, solar_w_m2=800,
               diameter_m=0.028, emissivity=0.5, absorptivity=0.5,
               r20_ohm_m=0.00008, alpha_per_c=0.00403):
    """Explicit educational heat balance; h must be calibrated for field use."""
    # A documented empirical teaching coefficient, NOT an IEEE 738 rating algorithm.
    h_w_m2_k = 5 + 10 * np.sqrt(max(0, wind_m_s))
    joule = current_a**2 * r20_ohm_m * (1 + alpha_per_c * (t - 20))
    solar = absorptivity * diameter_m * solar_w_m2
    convection = h_w_m2_k * np.pi * diameter_m * (t - ambient_c)
    radiation = emissivity * 5.670374419e-8 * np.pi * diameter_m * (
        (t + 273.15)**4 - (ambient_c + 273.15)**4)
    return joule + solar - convection - radiation


def thermal_demo():
    cfg = load_configs("config/lines.json")[0]
    net, _, _, i = build_pair(cfg, 132.1, 80, 16)
    values = {"tdpf": True, "alpha": cfg.alpha_per_c,
        "reference_temperature_degree_celsius": 20.0,
        "temperature_degree_celsius": 35.0, "air_temperature_degree_celsius": 35.0,
        "conductor_outer_diameter_m": 0.028, "mc_joule_per_m_k": 1000.0,
        "wind_speed_m_per_s": 0.6, "wind_angle_degree": 45.0,
        "solar_radiation_w_per_sq_m": 800.0, "solar_absorptivity": 0.5,
        "emissivity": 0.5}
    net.line["tdpf"] = False
    for k, v in values.items():
        net.line.at[i, k] = v
    pp.runpp(net, tdpf=True, tdpf_update_r_theta=True, tdpf_delay_s=600,
        numba=False, max_iteration=60, tolerance_mva=1e-8, lightsim2grid=False)
    r = net.res_line.loc[i]
    current = float(max(r.i_from_ka, r.i_to_ka) * 1000)
    steady_t = brentq(lambda t: heat_terms(t, current), 35, 300)
    solution = solve_ivp(lambda seconds, state: [heat_terms(state[0], current) / 1000],
                          (0, 600), [35], rtol=1e-8, atol=1e-8)
    # Rating in this teaching heat model only; operational ratings need certified data.
    limit = 80.0
    cooling_without_current = -heat_terms(limit, 0)
    teaching_limit = np.sqrt(max(0, cooling_without_current) / (
        cfg.r_ohm_per_km / 1000 * (1 + cfg.alpha_per_c * (limit - 20))))
    return {"data_origin": "synthetic", "current_a": current,
        "pandapower_600s_temperature_c": float(r.temperature_degree_celsius),
        "teaching_heat_model_600s_temperature_c": float(solution.y[0, -1]),
        "teaching_heat_model_steady_temperature_c": float(steady_t),
        "teaching_heat_model_80c_limit_a": float(teaching_limit),
        "operational_rating_validated": False}
