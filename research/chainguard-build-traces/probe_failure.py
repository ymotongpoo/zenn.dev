#!/usr/bin/env python3
"""Exercise CLI error exits and verify that the experimental root is exported."""
import json
import os
from pathlib import Path
import re
import subprocess

BASE = Path(__file__).resolve().parent

for tool, version in (("apko", "1.4.13"), ("melange", "0.63.2")):
    case = f"{tool}-failure"
    results = BASE / ".work" / "results"
    results.mkdir(parents=True, exist_ok=True)
    missing = BASE / ".work" / "nonexistent.yaml"
    assert not missing.exists()
    args = [str(BASE / ".work" / f"{tool}-otel"), "build", str(missing)]
    if tool == "apko":
        args += ["hello:failure", str(BASE / ".work" / "unused.tar")]
    else:
        args += ["--arch", "x86_64"]
    env = dict(os.environ, OTEL_TRACES_EXPORTER="otlp",
               OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:14317",
               OTEL_SERVICE_NAME=tool,
               OTEL_RESOURCE_ATTRIBUTES=f"experiment.case={case},service.version={version}")
    result = subprocess.run(args, cwd=BASE, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (results / f"{case}.log").write_text(result.stdout)
    assert result.returncode == 1, result.stdout
    match = re.search(r"TRACE service=(\S+) trace_id=([0-9a-f]{32})", result.stdout)
    assert match, result.stdout
    (results / f"{case}.json").write_text(json.dumps({
        "case": case, "exit_code": result.returncode,
        "service": match[1], "trace_id": match[2],
    }, indent=2) + "\n")
    print(case, match[2], "exit=1")
