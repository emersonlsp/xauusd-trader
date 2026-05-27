from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_jsonl(path: str, row: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts_utc": datetime.now(tz=UTC).isoformat(), **row}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def write_daily_summary(path: str, summary: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at_utc": datetime.now(tz=UTC).isoformat(), **summary}
    p.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

