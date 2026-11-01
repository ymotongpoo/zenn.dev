#!/usr/bin/env python3
"""Download fixed upstream sources and add only experimental trace startup."""
import hashlib
from pathlib import Path
import shutil
import tarfile
import urllib.request

BASE = Path(__file__).resolve().parent
SOURCES = {
    "apko": ("1.4.13", "120085477a56558cd89e3c1fd4bf07156a22bcfd0693fd097e0c3b3002b97887"),
    "melange": ("0.63.2", "052edaef6776a457fc594930f947e191ac7718eb5921f8a07a92792ecb74c49d"),
}


def prepare(tool, version, expected):
    work = BASE / ".work"
    work.mkdir(exist_ok=True)
    archive = work / f"{tool}-v{version}.tar.gz"
    if not archive.exists():
        urllib.request.urlretrieve(
            f"https://codeload.github.com/chainguard-dev/{tool}/tar.gz/refs/tags/v{version}", archive
        )
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"source checksum mismatch: {archive}")
    dest = work / f"{tool}-{version}"
    if (dest / "telemetry.go").exists():
        if (dest / "telemetry.go").read_bytes() != (BASE / "telemetry.go").read_bytes():
            raise RuntimeError(f"telemetry.go changed; update or move aside {dest} before preparing again")
        print(f"already prepared: {dest}")
        return
    with tarfile.open(archive) as tf:
        tf.extractall(work, filter="data")
    main = dest / "main.go"
    source = main.read_text()
    if tool == "apko":
        old = "return cli.New().ExecuteContext(ctx)"
        new = 'return runTraced(ctx, "apko", cli.New().ExecuteContext)'
    else:
        old = "if err := cli.New().ExecuteContext(ctx); err != nil {"
        new = 'if err := runTraced(ctx, "melange", cli.New().ExecuteContext); err != nil {'
    assert source.count(old) == 1, f"upstream entrypoint changed: {main}"
    main.write_text(source.replace(old, new))
    shutil.copyfile(BASE / "telemetry.go", dest / "telemetry.go")
    print(dest)


if __name__ == "__main__":
    for tool, (version, checksum) in SOURCES.items():
        prepare(tool, version, checksum)
