"""As of alignment before the frame enters the electrical twin."""
from datetime import datetime
from .contracts import Measurement, utc
from .importer import NUMERIC


def assemble_frame(envelope, samples, max_age_s=10, max_skew_s=2):
    """Samples are canonical units: signal -> list of time, value, quality, sigma."""
    asof = utc(datetime.fromisoformat(envelope["event_time"]))
    output = dict(envelope)
    for field in NUMERIC:
        output.pop(field, None)
    output["signal_quality"], output["uncertainty"] = {}, {}
    times = {}
    for signal, records in samples.items():
        parsed = [(utc(datetime.fromisoformat(r["event_time"])), r) for r in records]
        eligible = [(t, r) for t, r in parsed if t <= asof]
        if not eligible:
            output[signal] = None
            output["signal_quality"][signal] = "MISSING"
            continue
        when, record = max(eligible, key=lambda pair: pair[0])
        times[signal] = when.isoformat()
        age = (asof - when).total_seconds()
        output[signal] = record["value"] if age <= max_age_s else None
        output["signal_quality"][signal] = (
            record.get("quality", "SUSPECT") if age <= max_age_s else "MISSING")
        if "sigma" in record:
            output["uncertainty"][signal] = record["sigma"]
    selected = [datetime.fromisoformat(t) for k,t in times.items()
                if output["signal_quality"].get(k) == "GOOD"]
    skew = (max(selected)-min(selected)).total_seconds() if selected else None
    if skew is not None and skew > max_skew_s:
        for k in output["signal_quality"]:
            if output["signal_quality"][k] == "GOOD":
                output["signal_quality"][k] = "SUSPECT"
    output["source_metadata"] = {**output.get("source_metadata", {}),
        "per_signal_event_time": times, "alignment_skew_s": skew,
        "max_age_s": max_age_s, "max_skew_s": max_skew_s}
    return Measurement.model_validate(output)
