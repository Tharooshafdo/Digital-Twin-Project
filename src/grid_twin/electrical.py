"""Sectioned balanced electrical line, verified by cascaded ABCD matrices."""
import math
import cmath
import numpy as np
import pandapower as pp
from scipy.optimize import root
from .domain import LineParameters
from tl_twin.physics import solve_line, solve_abcd, resistance

def solve_sectioned(component, cfg, vs_kv, p_mw, q_mvar, temperature=None):
    p = LineParameters.model_validate(component["parameters"])
    if not p.sections:
        return solve_line(cfg, vs_kv, p_mw, q_mvar, temperature), solve_abcd(cfg, vs_kv, p_mw, q_mvar, temperature)
    net = pp.create_empty_network(f_hz=p.nominal_frequency_hz, sn_mva=100)
    buses = [pp.create_bus(net, p.nominal_kv) for _ in range(len(p.sections)+1)]
    pp.create_ext_grid(net, buses[0], vm_pu=vs_kv/p.nominal_kv)
    pp.create_load(net, buses[-1], p_mw=p_mw, q_mvar=q_mvar)
    factor = resistance(cfg, temperature)/cfg.r_ohm_per_km if cfg.r_ohm_per_km > 0 else (
        1 if temperature is None else 1+cfg.alpha_per_c*(temperature-cfg.reference_temperature_c))
    matrix = np.eye(2, dtype=complex)
    for i, s in enumerate(p.sections):
        pp.create_line_from_parameters(net, buses[i], buses[i+1], s.length_km,
            s.r_ohm_per_km*factor, s.x_ohm_per_km, s.c_nf_per_km, s.max_i_ka,
            g_us_per_km=s.g_us_per_km, parallel=p.parallel_circuits, df=p.derating_factor,
            type=s.line_type, name=s.name)
        z = complex(s.r_ohm_per_km*factor, s.x_ohm_per_km)*s.length_km/p.parallel_circuits
        y = complex(s.g_us_per_km*1e-6, 2*math.pi*p.nominal_frequency_hz*s.c_nf_per_km*1e-9)*s.length_km*p.parallel_circuits
        a = 1+y*z/2
        matrix = matrix @ np.array([[a,z],[y*(1+y*z/4),a]])
    pp.runpp(net, numba=False, calculate_voltage_angles=True, lightsim2grid=False,
             tolerance_mva=1e-9, max_iteration=40)
    first, last = net.res_line.iloc[0], net.res_line.iloc[-1]
    predicted = {"vr_ll_kv": float(net.res_bus.at[buses[-1],"vm_pu"]*p.nominal_kv),
        "vr_angle_deg":float(net.res_bus.at[buses[-1],"va_degree"]),"is_a":float(first.i_from_ka*1000),
        "ir_a":float(last.i_to_ka*1000),"p_send_mw":float(first.p_from_mw),"q_send_mvar":float(first.q_from_mvar),
        "p_recv_mw":float(-last.p_to_mw),"q_recv_mvar":float(-last.q_to_mvar),
        "loss_mw":float(net.res_line.pl_mw.sum()),"q_net_absorption_mvar":float(net.res_line.ql_mvar.sum()),
        "loading_percent":float(net.res_line.loading_percent.max()),"r_used_ohm_per_km":cfg.r_ohm_per_km*factor,
        "model_version":"balanced.sectioned.pi.pandapower3.5.5.v1",
        "sections":[{"name":s.name,"line_type":s.line_type,"loading_percent":float(net.res_line.at[i,"loading_percent"]),
                     "loss_mw":float(net.res_line.at[i,"pl_mw"]),"rating_source":s.rating_source} for i,s in enumerate(p.sections)]}
    vs=vs_kv*1000/math.sqrt(3);sr=complex(p_mw,q_mvar)*1e6
    a,b,c,d=matrix.flatten()
    def equations(x):
        vr=complex(*x)
        if abs(vr)<1:return [1e10,1e10]
        ir=(sr/(3*vr)).conjugate()
        mismatch=a*vr+b*ir-vs
        return [mismatch.real,mismatch.imag]
    answer=root(equations,[vs*.98,-vs*.03])
    if not answer.success or np.linalg.norm(equations(answer.x))>1e-4:
        raise ValueError("Cascaded independent ABCD did not converge")
    vr=complex(*answer.x);ir=(sr/(3*vr)).conjugate();is_=c*vr+d*ir;ss=3*vs*is_.conjugate()
    independent={"vr_ll_kv":abs(vr)*math.sqrt(3)/1000,"vr_angle_deg":math.degrees(cmath.phase(vr)),
        "is_a":abs(is_),"ir_a":abs(ir),"p_send_mw":ss.real/1e6,"q_send_mvar":ss.imag/1e6,
        "loss_mw":(ss.real-sr.real)/1e6,"abcd_determinant_error":float(abs(a*d-b*c-1))}
    return predicted, independent
