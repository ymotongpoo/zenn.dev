#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
case_name=${1:?usage: bash run.sh melange|apko [case-name]}
tool=$case_name
case_name=${2:-$tool}
if [[ $tool != melange && $tool != apko ]]; then
  echo 'tool must be melange or apko' >&2
  exit 2
fi
if [[ ! $case_name =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo 'case-name must contain only letters, digits, underscores, or hyphens' >&2
  exit 2
fi
runtime=cgr.dev/chainguard/melange@sha256:4bcc9f5ce0a97e333b9440473952126dd71e9f50b7800b92124c3a98496be7d8
mkdir -p .work/build .work/source .work/results
cp hello.yaml apko.yaml .work/build/
if [[ ! -f .work/build/melange.rsa ]]; then
  docker run --rm -v "$PWD/.work/build:/work" "$runtime" keygen
fi
if [[ ! -x .work/$tool-otel ]]; then
  echo 'run bash build.sh first' >&2
  exit 2
fi
tool_version=1.4.13
if [[ $tool == melange ]]; then
  tool_version=0.63.2
fi
opts=(--rm --network host
  -v "$PWD/.work/build:/work"
  -v "$PWD/.work/source:/source:ro"
  -v "$PWD/.work/$tool-otel:/experiment/$tool:ro"
  --entrypoint "/experiment/$tool"
  -e OTEL_TRACES_EXPORTER=otlp
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:14317
  -e "OTEL_SERVICE_NAME=$tool"
  -e "OTEL_RESOURCE_ATTRIBUTES=experiment.case=$case_name,service.version=$tool_version")
if [[ $tool == melange ]]; then
  opts+=(--privileged)
  args=(build hello.yaml --arch x86_64 --signing-key melange.rsa
    --source-dir /source --cache-dir /work/cache/melange-sources
    --apk-cache-dir /work/cache/melange-apk)
else
  args=(build apko.yaml hello:otel-experiment hello.tar --cache-dir /work/cache/apko)
fi
set +e
docker run "${opts[@]}" "$runtime" "${args[@]}" 2>&1 | tee ".work/results/$case_name.log"
status=${PIPESTATUS[0]}
set -e
python3 - "$case_name" "$status" <<'PY'
import json, re, sys
from pathlib import Path
case, status = sys.argv[1], int(sys.argv[2])
base = Path('.work/results')
text = (base / f'{case}.log').read_text()
match = re.search(r'TRACE service=(\S+) trace_id=([0-9a-f]{32})', text)
result = {'case': case, 'exit_code': status}
if match:
    result.update(service=match[1], trace_id=match[2])
(base / f'{case}.json').write_text(json.dumps(result, indent=2) + '\n')
PY
exit "$status"
