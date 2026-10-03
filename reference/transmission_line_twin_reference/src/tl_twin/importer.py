"""Strict CSV adapter; immutable dataset hash and original timestamps retained."""
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .contracts import Measurement

NUMERIC = {"vs_ll_kv", "vr_ll_kv", "is_a", "ir_a", "p_send_mw", "q_send_mvar",
           "p_recv_mw", "q_recv_mvar", "frequency_hz", "conductor_temp_c"}


def import_csv(csv_path, mapping_path, output_path):
    raw = Path(csv_path).read_bytes()
    dataset = "sha256:" + hashlib.sha256(raw).hexdigest()
    mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
    mapping_hash = hashlib.sha256(Path(mapping_path).read_bytes()).hexdigest()
    timezone = ZoneInfo(mapping["timezone"])
    records, errors = [], []
    with open(csv_path, encoding="utf-8-sig", newline="") as handle:
        for sequence, row in enumerate(csv.DictReader(handle)):
            try:
                original = row[mapping["timestamp_column"]]
                when = datetime.fromisoformat(original)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone)
                base = {"message_id": hashlib.sha256(
                            f"{dataset}:{mapping_hash}:{sequence}".encode()).hexdigest(),
                        "dataset_id": dataset, "sequence_no": sequence,
                        "event_time": when, "original_timestamp": original,
                        "asset_id": row.get(mapping.get("asset_column", ""))
                            or mapping["asset_id"],
                        "source_id": mapping["source_id"] + ".map." + mapping_hash[:12],
                        "data_origin": mapping["data_origin"],
                        "connection_state": row.get(mapping.get("state_column", ""))
                            or mapping.get("connection_state", "UNKNOWN"),
                        "signal_quality": {}, "uncertainty": {},
                        "source_metadata": {"row_number": sequence + 2,
                                            "source_file_sha256": dataset[7:],
                                            "logical_source_id": mapping["source_id"],
                                            "adapter_version": "csv.adapter.v1",
                                            "mapping_sha256": mapping_hash}}
                for signal, spec in mapping["signals"].items():
                    if signal not in NUMERIC:
                        raise ValueError(f"Unknown numeric signal {signal}")
                    value = row.get(spec["column"], "").strip()
                    base[signal] = (None if value == "" else
                        float(value) * spec.get("scale", 1) + spec.get("offset", 0))
                    quality_column = spec.get("quality_column")
                    if quality_column:
                        raw_quality = row.get(quality_column, "")
                        base["signal_quality"][signal] = spec.get("quality_map", {}).get(
                            raw_quality, "SUSPECT")
                    else:
                        base["signal_quality"][signal] = (
                            "GOOD" if value else "MISSING")
                    if "sigma" in spec:
                        base["uncertainty"][signal] = spec["sigma"]
                records.append(Measurement.model_validate(base))
            except Exception as exc:
                errors.append({"row_number": sequence + 2,
                               "reason": str(exc), "raw": row})
    records.sort(key=lambda m: (m.event_time, m.asset_id, m.sequence_no))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("".join(
        m.model_dump_json() + "\n" for m in records), encoding="utf-8")
    Path(str(output_path) + ".rejects.json").write_text(
        json.dumps(errors, indent=2), encoding="utf-8")
    Path(str(output_path) + ".manifest.json").write_text(json.dumps({
        "dataset_id": dataset, "accepted_rows": len(records),
        "rejected_rows": len(errors), "mapping": mapping,
        "mapping_sha256": mapping_hash
    }, indent=2), encoding="utf-8")
    return len(records), len(errors)
