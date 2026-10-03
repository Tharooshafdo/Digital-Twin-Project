"""Level-span static sag geometry; tension at each temperature is an INPUT."""
import math


def sag_catenary(span_m, weight_n_per_m, horizontal_tension_n):
    if min(span_m,weight_n_per_m,horizontal_tension_n)<=0:
        raise ValueError("Span, weight and horizontal tension must be positive")
    a=horizontal_tension_n/weight_n_per_m
    exact=a*(math.cosh(span_m/(2*a))-1)
    approximate=weight_n_per_m*span_m**2/(8*horizontal_tension_n)
    return {"sag_catenary_m":exact,"sag_parabolic_m":approximate,
        "parabolic_relative_error":abs(approximate-exact)/exact,
        "tension_source_required":True,"clearance_validated":False}
