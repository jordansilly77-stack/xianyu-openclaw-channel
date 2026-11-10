"""离线回放和本机模型预览。不读取私信，不连接闲鱼，不发送。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from kefu_offline.engine import FIXTURE_DIR, load_catalog, run_replay
from kefu_offline.http_api import list_reviews
from kefu_offline.live import production_preview_turn
from kefu_offline.model_client import missing_model_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="待审客服回放。不会连接闲鱼，也不会发送。"
    )
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--replay", type=Path, default=None)
    parser.add_argument("--generator", choices=("rules", "mock"), default="rules")
    parser.add_argument("--mac-preview", action="store_true")
    parser.add_argument("--list-reviews", action="store_true")
    args = parser.parse_args(argv)
    if args.mac_preview:
        return mac_preview(args.catalog, args.replay)
    if args.list_reviews:
        json.dump(list_reviews(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    catalog = load_catalog(args.catalog or FIXTURE_DIR / "example_catalog.json")
    cases = json.loads((args.replay or FIXTURE_DIR / "replay_messages.json").read_text(encoding="utf-8"))
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


def case_to_wire(case: dict) -> dict:
    wire = case.get("wire")
    if isinstance(wire, dict):
        return wire
    item_id = str(case.get("item_id") or "").strip()
    url = f"fleamarket://message_chat?itemId={item_id}&peerUserId=900000000001" if item_id else ""
    chat = str(case.get("conversation_id") or case.get("id") or "preview")
    return {
        "1": {
            "10": {
                "senderUserId": "900000000001",
                "senderNick": "模拟买家",
                "reminderContent": case.get("text") or "",
                "reminderUrl": url,
            },
            "2": f"{chat}@goofish",
            "5": 1700000000000,
        },
        "3": {},
    }


def mac_preview(catalog: Optional[Path] = None, replay: Optional[Path] = None) -> int:
    """本机模型预览。单条或 --replay 批量都走 production_preview_turn，不连接闲鱼。"""
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
    os.environ["KEFU_CATALOG_PATH"] = str(catalog or FIXTURE_DIR / "mac_preview_catalog.yml")
    os.environ.setdefault("KEFU_REVIEW_PATH", "data/kefu_mac_preview.jsonl")
    if replay is None:
        wire = json.loads((FIXTURE_DIR / "mac_preview_wire.json").read_text(encoding="utf-8"))
        cases = [{"id": "mac-preview", "wire": wire}]
    else:
        cases = json.loads(Path(replay).read_text(encoding="utf-8"))
    results = []
    for case in cases:
        started = time.perf_counter()
        record = production_preview_turn(case_to_wire(case))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        results.append(
            {
                "id": case.get("id"),
                "status": record.get("status"),
                "reason": record.get("reason"),
                "buyer_visible_draft": record.get("buyer_visible_draft"),
                "model_invoked": bool(record.get("model_invoked")),
                "model_adopted": bool(record.get("model_adopted")),
                "model_rejected": bool(record.get("model_rejected")),
                "model_error": record.get("model_error"),
                "elapsed_ms": elapsed_ms,
                "send_allowed": False,
                "transport_send": False,
            }
        )
    payload = {
        "send_allowed": False,
        "transport_send": False,
        "xianyu_transport": "isolated",
        "cases": results,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if any(item.get("model_error") for item in results):
        return 1
    if any(item["status"] == "pending_review" and not item["model_invoked"] for item in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
