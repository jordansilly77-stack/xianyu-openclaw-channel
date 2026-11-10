"""离线回放和本机模型预览。不读取私信，不连接闲鱼，不发送。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from kefu_offline.engine import FIXTURE_DIR, load_catalog, run_replay
from kefu_offline.http_api import list_reviews
from kefu_offline.live import production_preview_turn
from kefu_offline.model_client import missing_model_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="待审客服回放。不会连接闲鱼，也不会发送。"
    )
    parser.add_argument("--catalog", type=Path, default=FIXTURE_DIR / "example_catalog.json")
    parser.add_argument("--replay", type=Path, default=FIXTURE_DIR / "replay_messages.json")
    parser.add_argument("--generator", choices=("rules", "mock"), default="rules")
    parser.add_argument("--mac-preview", action="store_true")
    parser.add_argument("--list-reviews", action="store_true")
    args = parser.parse_args(argv)
    if args.mac_preview:
        return mac_preview()
    if args.list_reviews:
        json.dump(list_reviews(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

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


def mac_preview() -> int:
    """父在 Mac 上执行的单次真实模型预览。模拟消息走生产识别和待审路径。"""
    missing = missing_model_env()
    if missing:
        json.dump(
            {
                "ok": False,
                "send_allowed": False,
                "missing_env": missing,
                "hint": "在 Mac 上设置 OPENAI_BASE_URL、OPENAI_API_KEY、OPENAI_MODEL 后再运行。不要把密钥写进仓库。",
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return 2
    os.environ["KEFU_MODEL_MODE"] = "openai"
    os.environ.pop("XIANYU_ALLOW_SEND", None)
    os.environ["KEFU_CATALOG_PATH"] = str(FIXTURE_DIR / "mac_preview_catalog.yml")
    os.environ.setdefault("KEFU_REVIEW_PATH", "data/kefu_mac_preview.jsonl")
    wire = json.loads((FIXTURE_DIR / "mac_preview_wire.json").read_text(encoding="utf-8"))
    record = production_preview_turn(wire)
    public = {key: value for key, value in record.items() if "key" not in key.lower() and "token" not in key.lower()}
    public["send_allowed"] = False
    public["transport_send"] = False
    public["xianyu_transport"] = "isolated"
    json.dump(public, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if public.get("model_error"):
        return 1
    return 0 if public.get("model_invoked") else 1


if __name__ == "__main__":
    raise SystemExit(main())
