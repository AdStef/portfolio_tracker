import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build_config(data_dir=None) -> dict:
    data = Path(data_dir or os.environ.get("PT_DATA_DIR") or ROOT / "data")
    return {
        "DATA_DIR": data,
        "DATABASE": data / "portfolio.db",
        "SNAPSHOT_DIR": data / "snapshots",
        "IMPORT_DIR": data / "imports",
        "MAX_CONTENT_LENGTH": 10 * 1024 * 1024,  # CSV uploads
    }
