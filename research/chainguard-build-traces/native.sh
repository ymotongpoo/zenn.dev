#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
runtime=cgr.dev/chainguard/melange@sha256:4bcc9f5ce0a97e333b9440473952126dd71e9f50b7800b92124c3a98496be7d8
mkdir -p .work/native .work/source
cp hello.yaml .work/native/
if [[ ! -f .work/native/melange.rsa ]]; then
  docker run --rm -v "$PWD/.work/native:/work" "$runtime" keygen
fi
docker run --privileged --rm \
  -v "$PWD/.work/native:/work" -v "$PWD/.work/source:/source:ro" \
  "$runtime" build hello.yaml --arch x86_64 --signing-key melange.rsa \
  --source-dir /source --trace native-trace.json 2>&1 | tee .work/native-build.log
