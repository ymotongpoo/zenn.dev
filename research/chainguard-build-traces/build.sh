#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 prepare.py
export CGO_ENABLED=0 GOMAXPROCS=2 GOFLAGS=-p=2
for spec in apko:1.4.13:217f25a71fd6f18f00fb1024f9b251dc7127bfd5 melange:0.63.2:402004649f817966440662612d0ea7302b95a858; do
  tool=${spec%%:*}
  rest=${spec#*:}
  version=${rest%%:*}
  source_sha=${rest#*:}
  (
    cd ".work/$tool-$version"
    go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc@v1.47.0 \
      go.opentelemetry.io/otel/sdk@v1.47.0
    go build -trimpath -buildvcs=false \
      -ldflags "-X sigs.k8s.io/release-utils/version.gitVersion=v$version-otel-experiment -X sigs.k8s.io/release-utils/version.gitCommit=$source_sha -X sigs.k8s.io/release-utils/version.gitTreeState=dirty" \
      -o "../$tool-otel" .
    go version -m "../$tool-otel" > "../$tool-build-info.txt"
  )
done
