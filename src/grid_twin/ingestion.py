"""Bounded strict CSV import with per-row rejects and deterministic identities."""
import csv
import io
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
from tl_twin.contracts import Measurement
from tl_twin.importer import NUMERIC
from .db import digest

def parse_csv(raw_text, mapping):
    required={"timezone","timestamp_column","asset_id","source_id","data_origin","signals"}
    missing=required-set(mapping)
    if missing:raise ValueError("Mapping missing required fields: "+", ".join(sorted(missing)))
    dataset = "sha256:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    mapping_hash = digest(mapping)
    try:tz = ZoneInfo(mapping["timezone"])
    except Exception as exc:raise ValueError("Unknown source timezone") from exc
    delimiter = mapping.get("delimiter", ",")
    if len(delimiter) != 1:
        raise ValueError("Delimiter must be one character")
    reader = csv.DictReader(io.StringIO(raw_text.lstrip("\ufeff")), delimiter=delimiter)
    frames, rejects = [], []
    for sequence, row in enumerate(reader):
        if sequence >= 10000:
            raise ValueError("Import limited to 10,000 rows; partition larger datasets")
        try:
            original = row[mapping["timestamp_column"]]
            when = datetime.strptime(original, mapping["date_format"]) if mapping.get("date_format") else datetime.fromisoformat(original)
            if when.tzinfo is None:
                when = when.replace(tzinfo=tz)
                if when.utcoffset() != when.replace(fold=1).utcoffset():
                    raise ValueError("Ambiguous/nonexistent local time; supply explicit UTC offset")
            state = row.get(mapping.get("state_column", "")) or mapping.get("connection_state", "UNKNOWN")
            frame = dict(message_id=hashlib.sha256(f"{dataset}:{mapping_hash}:{sequence}".encode()).hexdigest(),
                asset_id=row.get(mapping.get("asset_column", "")) or mapping["asset_id"],
                event_time=when, source_id=mapping["source_id"] + ".map." + mapping_hash[:12],
                dataset_id=dataset, data_origin=mapping["data_origin"], sequence_no=sequence,
                original_timestamp=original, connection_state=mapping.get("state_map", {}).get(state, state),
                signal_quality={}, uncertainty={}, source_metadata={"row_number": sequence+2,
                    "mapping_version": mapping_hash, "adapter_version": "csv.adapter.v2",
                    "declared_timezone": mapping["timezone"], "original_row": row,
                    "terminal_directions": mapping.get("terminal_directions", "receiving P/Q positive out")})
            if "power_error_correlation" in mapping:
                rho=float(mapping["power_error_correlation"])
                if not -1 <= rho <= 1:
                    raise ValueError("Power error correlation must be in [-1,1]")
                frame["source_metadata"]["power_error_correlation"]=rho
            for signal, spec in mapping["signals"].items():
                if signal not in NUMERIC:
                    raise ValueError(f"Unknown signal {signal}")
                text = row.get(spec["column"], "").strip()
                missing = text in ["", *map(str, spec.get("missing_sentinels", []))]
                frame[signal] = None if missing else (float(text) * spec.get("scale", 1) * spec.get("ct_ratio", 1) * spec.get("pt_ratio", 1) + spec.get("offset", 0)) * spec.get("direction", 1)
                if spec.get("direction", 1) not in (-1, 1):
                    raise ValueError("Terminal direction must be +1 or -1")
                quality = "MISSING" if missing else "GOOD"
                if spec.get("quality_column") and not missing:
                    quality = spec.get("quality_map", {}).get(row.get(spec["quality_column"]), "SUSPECT")
                frame["signal_quality"][signal] = quality
                if "sigma" in spec:
                    frame["uncertainty"][signal] = spec["sigma"]
            frames.append(Measurement.model_validate(frame).model_dump(mode="json"))
        except Exception as exc:
            rejects.append({"row_number": sequence+2, "reason": str(exc), "raw": row})
    frames.sort(key=lambda m: (m["event_time"], m["asset_id"], m["sequence_no"]))
    return {"frames": frames, "rejects": rejects,
        "manifest": {"dataset_id": dataset, "mapping_sha256": mapping_hash, "schema_version": "line.measurement.v1",
            "accepted_rows": len(frames), "rejected_rows": len(rejects), "mapping": mapping}}
