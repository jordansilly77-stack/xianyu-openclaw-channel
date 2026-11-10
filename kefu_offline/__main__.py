"""离线回放。不读取私信，不连接闲鱼，不发送。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kefu_offline.engine import FIXTURE_DIR, load_catalog, run_replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="用示例商品回放待审客服。不会发送，也不会调用模型。"
    )
    parser.add_argument("--catalog", type=Path, default=FIXTURE_DIR / "example_catalog.json")
    parser.add_argument("--replay", type=Path, default=FIXTURE_DIR / "replay_messages.json")
    parser.add_argument("--generator", choices=("rules", "mock"), default="rules")
    args = parser.parse_args(argv)

    catalog = load_catalog(args.catalog)
    cases = json.loads(args.replay.read_text(encoding="utf-8"))
    decisions, failures = run_replay(catalog, cases, generator=args.generator)
    summary = {
        "catalog_id": catalog.catalog_id,
        "generator": args.generator,
        "model_invoked": False,
        "send_allowed": False,
        "cases": len(decisions),
        "failed": len(failures),
        "results": [item.to_dict() for item in decisions],
        "failures": failures,
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
