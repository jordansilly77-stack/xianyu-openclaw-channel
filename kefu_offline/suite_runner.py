"""多轮逻辑套件。走 production_preview_turn，不连接闲鱼，不发送。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from kefu_offline.live import note_seller_fact, production_preview_turn, reset_runtime_state
from kefu_offline.style import BANNED_PHRASES


class EchoModel:
    """假模型：原样返回规则草稿。云端测试用，不是用户的真实网关。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        payload = json.loads(messages[-1]["content"])
        return str(payload.get("rule_draft") or "")


class BudgetModel:
    def __init__(self, inner: Any, max_calls: int) -> None:
        self.inner = inner
        self.max_calls = max_calls
        self.calls = 0

    def complete(self, messages: list[dict[str, str]]) -> str:
        if self.calls >= self.max_calls:
            raise RuntimeError("model_budget")
        self.calls += 1
        return self.inner.complete(messages)


_IN_STOCK = ("在售", "在的", "还有", "有的")
_SOLD = ("卖出", "没了", "售出")
JUDGMENT_VERSION = "2026-11-10-price-vs-delivery"


def evaluate_turn(record: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    draft = str(record.get("buyer_visible_draft") or "")
    availability = expect.get("availability")
    if availability == "in_stock":
        if not any(phrase in draft for phrase in _IN_STOCK):
            failures.append("not available")
        if any(phrase in draft for phrase in _SOLD):
            failures.append("said sold")
    elif availability == "sold":
        if not any(phrase in draft for phrase in _SOLD):
            failures.append("not sold")
        if any(phrase in draft for phrase in _IN_STOCK):
            failures.append("sold but said available")
    if expect.get("status") and record.get("status") != expect["status"]:
        failures.append(f"status {record.get('status')} != {expect['status']}")
    if expect.get("reason") and record.get("reason") != expect["reason"]:
        failures.append(f"reason {record.get('reason')} != {expect['reason']}")
    if "model" in expect and bool(record.get("model_invoked")) != bool(expect["model"]):
        failures.append(f"model_invoked {record.get('model_invoked')} != {expect['model']}")
    if record.get("send_allowed") or record.get("transport_send"):
        failures.append("send flag opened")
    for snippet in expect.get("contain") or []:
        if not snippet or snippet not in draft:
            failures.append(f"missing {snippet}")
    for snippet in expect.get("absent") or []:
        if snippet and snippet in draft:
            failures.append(f"forbidden {snippet}")
    for phrase in BANNED_PHRASES:
        if phrase in draft:
            failures.append(f"banned {phrase}")
    if expect.get("negation") and "不行" not in draft:
        failures.append("missing negation")
    if expect.get("one_question") and draft.count("？") > 1:
        failures.append("more than one question")
    return failures


def reevaluate_checkpoint(path: Path, sessions: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """用当前断言重读已有 checkpoint。不调用模型，不改原文件。"""
    if sessions is None:
        from kefu_offline.fixtures.sim_logic_suite import build_suite

        sessions = build_suite()
    expects: dict[str, dict[str, Any]] = {}
    for session in sessions:
        for index, turn in enumerate(session["turns"], start=1):
            expects[f"{session['id']}-{index}"] = turn
    source = Path(path)
    raw = source.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    original_failed = 0
    original_final_failed = 0
    reeval_failed = 0
    flipped: list[dict[str, Any]] = []
    still_failed: list[dict[str, Any]] = []
    new_failed: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for row in rows:
        stored_fail = _stored_failed(row)
        if stored_fail:
            original_failed += 1
        if _stored_final_failed(row):
            original_final_failed += 1
        turn_id = str(row.get("turn_id") or "")
        turn = expects.get(turn_id)
        if turn is None:
            unmatched.append(turn_id)
            continue
        draft = row.get("final_draft")
        if draft is None:
            draft = row.get("draft")
        if draft is None:
            draft = row.get("buyer_visible_draft") or ""
        record = {
            "buyer_visible_draft": draft,
            "status": row.get("status"),
            "reason": row.get("reason"),
            "model_invoked": row.get("model_invoked"),
            "send_allowed": row.get("send_allowed"),
            "transport_send": bool(row.get("transport_send")),
        }
        failures = evaluate_turn(record, turn["expect"])
        if failures:
            reeval_failed += 1
        item = {
            "turn_id": turn_id,
            "text": row.get("text") or turn.get("text"),
            "draft": draft,
            "original_failures": list(row.get("failures") or []),
            "reeval_failures": failures,
        }
        if stored_fail and not failures:
            flipped.append(item)
        elif stored_fail and failures:
            still_failed.append(item)
        elif not stored_fail and failures:
            new_failed.append(item)
    if source.read_bytes() != raw:
        raise RuntimeError("reeval must not modify the checkpoint")
    reeval_exit = 0 if reeval_failed == 0 and not unmatched else 1
    return {
        "judgment_version": JUDGMENT_VERSION,
        "source_checkpoint": str(source),
        "source_bytes": len(raw),
        "source_mutated": False,
        "model_calls": 0,
        "turns": len(rows),
        "unmatched": unmatched,
        "original": {
            "failed": original_failed,
            "final_failed": original_final_failed,
            "exit_code": 0 if original_failed == 0 else 1,
        },
        "reeval": {"failed": reeval_failed, "exit_code": reeval_exit},
        "flipped_to_pass": flipped,
        "still_failed": still_failed,
        "new_failed": new_failed,
    }


def _stored_failed(row: dict[str, Any]) -> bool:
    if "ok" in row:
        return not bool(row.get("ok"))
    return bool(row.get("failures"))


def _stored_final_failed(row: dict[str, Any]) -> bool:
    if "final_ok" in row:
        return not bool(row.get("final_ok"))
    return _stored_failed(row)


def run_suite(
    sessions: list[dict[str, Any]],
    *,
    model_client: Any = None,
    max_model_calls: int = 180,
    timeout_budget_s: float = 600,
    checkpoint: Optional[Path] = None,
    resume: bool = False,
) -> dict[str, Any]:
    os.environ["KEFU_SUITE_TRACE"] = "1"
    reset_runtime_state()
    done: dict[str, dict[str, Any]] = {}
    if resume and checkpoint and checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("ok"):
                done[row["turn_id"]] = row
    client = model_client
    if client is not None:
        client = BudgetModel(client, max_model_calls)
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    schedule = _schedule(sessions)
    for turn in schedule:
        turn_id = turn["turn_id"]
        if turn_id in done:
            _restore(done[turn_id])
            results.append(done[turn_id])
            continue
        if turn.get("seller_update"):
            note_seller_fact(turn["seller_update"]["item_id"], **turn["seller_update"]["fields"])
        elapsed_budget = time.perf_counter() - started
        over_time = elapsed_budget > timeout_budget_s
        call_client = None if over_time else client
        t0 = time.perf_counter()
        try:
            from kefu_offline.__main__ import case_to_wire
            record = production_preview_turn(
                case_to_wire(turn),
                cookie_id=turn.get("cookie_id") or "suite",
                sender_id=turn.get("sender_id") or "buyer-sim",
                message_id=turn.get("message_id"),
                model_client=call_client,
            )
            error = None
        except Exception as exc:  # noqa: BLE001 - 保留这一轮的失败，不自动重试
            record = {"buyer_visible_draft": "", "model_invoked": False, "send_allowed": False, "transport_send": False}
            error = type(exc).__name__
        row = {
            "turn_id": turn_id,
            "session_id": turn["session_id"],
            "conversation_id": turn["conversation_id"],
            "cookie_id": turn.get("cookie_id") or "suite",
            "matched_item_id": record.get("matched_item_id"),
            "text": turn.get("text"),
            "draft": record.get("buyer_visible_draft"),
            "final_draft": record.get("buyer_visible_draft"),
            "model_candidate": record.get("model_candidate"),
            "reject_reasons": record.get("reject_reasons") or [],
            "status": record.get("status"),
            "reason": record.get("reason"),
            "model_invoked": bool(record.get("model_invoked")),
            "model_adopted": bool(record.get("model_adopted")),
            "model_rejected": bool(record.get("model_invoked")) and bool(record.get("model_rejected")),
            "inherited_model_rejected": bool(record.get("inherited_model_rejected")),
            "reject_source": record.get("reject_source"),
            "model_error": record.get("model_error") or error,
            "duplicate": bool(record.get("duplicate")),
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            "human_review": bool(turn.get("human_review")),
            "send_allowed": False,
        }
        if over_time and turn["expect"].get("model"):
            row["model_error"] = "timeout_budget"
        failures = evaluate_turn(record, turn["expect"])
        if error:
            failures.append(error)
        if over_time and turn["expect"].get("model") and not record.get("model_invoked"):
            failures.append("timeout_budget")
        row["failures"] = failures
        row["final_ok"] = not failures
        row["model_output_ok"] = (
            None if not record.get("model_invoked") else not bool(record.get("model_rejected"))
        )
        row["guard_blocked"] = row["model_rejected"] and row["final_ok"]
        row["ok"] = not failures
        results.append(row)
        if checkpoint:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = _summarize(sessions, results)
    summary["elapsed_s"] = round(time.perf_counter() - started, 2)
    return summary


def _schedule(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    plain: list[dict[str, Any]] = []
    for session in sessions:
        group = session.get("interleave")
        if group:
            grouped.setdefault(group, []).append(session)
        else:
            plain.extend(_expand(session))
    ordered = list(plain)
    for sessions_in_group in grouped.values():
        expanded = [_expand(session) for session in sessions_in_group]
        width = max(len(item) for item in expanded)
        for index in range(width):
            for item in expanded:
                if index < len(item):
                    ordered.append(item[index])
    return ordered


def _expand(session: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, turn in enumerate(session["turns"], start=1):
        rows.append(
            {
                **turn,
                "session_id": session["id"],
                "conversation_id": session["conversation_id"],
                "cookie_id": session.get("cookie_id") or "suite",
                "sender_id": session.get("sender_id") or "buyer-sim",
                "turn_id": f"{session['id']}-{index}",
            }
        )
    return rows


def _restore(row: dict[str, Any]) -> None:
    from kefu_offline import live as live_mod

    key = (row.get("cookie_id") or "suite", row["conversation_id"])
    if row.get("matched_item_id"):
        live_mod._BOUND[key] = row["matched_item_id"]
    live_mod._HISTORY.setdefault(key, [])
    live_mod._HISTORY[key].extend(
        [
            {"role": "buyer", "text": row.get("text") or "", "trusted": "false"},
            {"role": "seller", "text": row.get("draft") or "", "trusted": "true"},
        ]
    )


def _summarize(sessions: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    categories = {session.get("category") for session in sessions if session.get("category")}
    return {
        "simulated": True,
        "xianyu_transport": "isolated",
        "sessions": len(sessions),
        "turns": len(results),
        "categories": len(categories),
        "model_invoked": sum(1 for row in results if row.get("model_invoked")),
        "model_adopted": sum(1 for row in results if row.get("model_adopted")),
        "model_rejected": sum(1 for row in results if row.get("model_rejected")),
        "inherited_guard": sum(1 for row in results if row.get("inherited_model_rejected")),
        "model_error": sum(1 for row in results if row.get("model_error")),
        "rule_skipped": sum(1 for row in results if not row.get("model_invoked")),
        "duplicate": sum(1 for row in results if row.get("duplicate")),
        "failed": sum(1 for row in results if not row.get("ok")),
        "final_failed": sum(1 for row in results if not row.get("final_ok")),
        "guard_blocked": sum(1 for row in results if row.get("guard_blocked")),
        "model_output_rejected": sum(1 for row in results if row.get("model_output_ok") is False),
        "human_review": sum(1 for row in results if row.get("human_review")),
        "send_allowed": False,
        "results": results,
    }
