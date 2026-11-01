#!/usr/bin/env python3
"""Verify collected real traces, then write a small shareable evidence file."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
cases = ["melange-first", "melange-repeat", "apko-first", "apko-repeat",
         "melange-failure", "apko-failure"]
observations = []
for case in cases:
    summary = json.loads((BASE / ".work" / "results" / f"{case}.summary.json").read_text())
    tool = case.split("-")[0]
    failed = case.endswith("-failure")
    assert summary["exit_code"] == (1 if failed else 0), case
    assert summary["root_names"] == [f"{tool} build"], case
    assert not summary["missing_parent_names"], case
    assert not summary["negative_duration_names"], case
    assert len(summary["resource_attributes"]) == 1, case
    resource = summary["resource_attributes"][0]
    assert resource["service.name"] == tool, case
    assert resource["experiment.case"] == case, case
    root = next(span for span in summary["major_spans"] if span["name"] == f"{tool} build")
    if failed:
        assert root["status"]["code"] == "STATUS_CODE_ERROR", case
    else:
        for scope in (tool, "apko", "go-apk"):
            assert summary["scopes"].get(scope, 0) > 0, (case, scope)
    observations.append({key: summary[key] for key in (
        "case", "exit_code", "trace_id", "span_count", "scopes", "major_spans",
        "missing_parent_names", "negative_duration_names", "resource_attributes",
    )})
assert len({item["trace_id"] for item in observations}) == len(cases)
native = [json.loads(line) for line in
          (BASE / ".work" / "native" / "native-trace.json").read_text().splitlines() if line.strip()]
output = (BASE / ".work" / "hello-output.txt").read_text()
assert output.strip() == "Hello, world!"
evidence = {
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "method": "Real GNU Hello builds; spans retrieved from Tempo HTTP API, without browser verification.",
    "versions": {"melange": "v0.63.2", "apko": "v1.4.13", "otel_go": "v1.47.0",
                 "go": "go1.27.0", "otel_lgtm": "0.37.0", "tempo": "3.1.0"},
    "native_melange": {"span_count": len(native),
                       "scopes": dict(Counter(s["InstrumentationScope"]["Name"] for s in native)),
                       "span_names": sorted({s["Name"] for s in native})},
    "cases": observations,
    "container_stdout": output,
}
(BASE / "results.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
print(f"PASS: {len(cases)} real traces, unique trace IDs, complete parents, resources, failure status, Hello output")
