#!/usr/bin/env python3
"""Summarize a real Tempo trace, retaining its raw response under .work/."""
import argparse
from collections import Counter
import json
from pathlib import Path
import urllib.request

BASE = Path(__file__).resolve().parent


def value(v):
    for key in ("stringValue", "intValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    return v


def attributes(items):
    return {item["key"]: value(item["value"]) for item in items}


def summarize(case, endpoint):
    results = BASE / ".work" / "results"
    state = json.loads((results / f"{case}.json").read_text())
    trace_id = state["trace_id"]
    request = urllib.request.Request(
        f"{endpoint}/api/v2/traces/{trace_id}", headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    (results / f"{case}.tempo.json").write_bytes(raw)
    trace = json.loads(raw)
    if "trace" in trace:
        trace = trace["trace"]
    spans = []
    resources = []
    for batch in trace.get("resourceSpans", trace.get("batches", [])):
        resources.append(attributes(batch.get("resource", {}).get("attributes", [])))
        for group in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", [])):
            scope = group.get("scope", group.get("instrumentationLibrary", {})).get("name", "")
            for span in group.get("spans", []):
                span = dict(span, scope=scope)
                span["start"] = int(span["startTimeUnixNano"])
                span["end"] = int(span["endTimeUnixNano"])
                spans.append(span)
    if not spans:
        raise RuntimeError("Tempo returned no spans")
    ids = {span["spanId"] for span in spans}
    roots = [span for span in spans if not span.get("parentSpanId")
             or set(span["parentSpanId"]) == {"0"}]
    missing = [span["name"] for span in spans
               if span.get("parentSpanId") and span not in roots and span["parentSpanId"] not in ids]
    major = []
    for span in spans:
        if span["scope"] == "go-apk":
            continue
        major.append({"name": span["name"], "scope": span["scope"],
                      "duration_ms": round((span["end"] - span["start"]) / 1e6, 3),
                      "status": span.get("status", {})})
    summary = {
        **state,
        "span_count": len(spans),
        "root_names": [span["name"] for span in roots],
        "missing_parent_names": missing,
        "negative_duration_names": [span["name"] for span in spans if span["end"] < span["start"]],
        "resource_attributes": [dict(items) for items in {tuple(sorted(r.items())) for r in resources}],
        "scopes": dict(Counter(span["scope"] for span in spans)),
        "major_spans": sorted(major, key=lambda span: span["duration_ms"], reverse=True),
        "span_names": dict(sorted(Counter(span["name"] for span in spans).items())),
        "tempo_api_url": f"{endpoint}/api/v2/traces/{trace_id}",
    }
    (results / f"{case}.summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in
                      ("case", "trace_id", "span_count", "root_names", "scopes", "missing_parent_names")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case")
    parser.add_argument("--tempo", default="http://127.0.0.1:14320")
    args = parser.parse_args()
    summarize(args.case, args.tempo)
