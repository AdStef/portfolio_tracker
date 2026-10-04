"""Reads/writes the precomputed JSON files the dashboard is served from."""

import json
import os
import tempfile
from pathlib import Path

ENGINE_VERSION = 1
FILES = ("dashboard", "history")


def write(snapshot_dir: Path, meta: dict, result: dict) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    meta = {**meta, "engine_version": ENGINE_VERSION}
    for name in FILES:
        _atomic_write(snapshot_dir / f"{name}.json", {"meta": meta, **result[name]})


def read(snapshot_dir: Path, name: str) -> dict | None:
    path = snapshot_dir / f"{name}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
