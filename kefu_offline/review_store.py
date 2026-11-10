"""待审草稿落盘。只追加记录，不发送。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def review_path(explicit: Optional[Path] = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("KEFU_REVIEW_PATH", "").strip()
    if env:
        return Path(env)
    return Path("data/kefu_reviews.jsonl")


class ReviewStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = review_path(path)

    def append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def list_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records
