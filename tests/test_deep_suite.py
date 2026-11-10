"""深测与工期/附加费护栏。假模型和脚本坏候选不是 Mac 真网关结果。"""

import json

from kefu_offline.fixtures.sim_logic_suite import build_suite, deep_suite, style_suite, suite_counts, write_catalog
from kefu_offline.live import handle_live_message, reset_runtime_state
from kefu_offline.model_client import ModelCallError
from kefu_offline.suite_runner import EchoModel, evaluate_turn, run_suite


def _draft(text: str, *, model: bool = True, status: str = "pending_review") -> dict:
    return {
        "status": status,
        "buyer_visible_draft": text,
        "model_invoked": model,
        "send_allowed": False,
        "transport_send": False,
    }


def _expect(suite, session_id: str, text: str) -> dict:
    session = next(item for item in suite if item["id"] == session_id)
    return next(turn["expect"] for turn in session["turns"] if turn["text"] == text)


def test_deep_suite_is_separate_and_bounded():
    base = suite_counts(build_suite())
    deep = suite_counts(deep_suite())
    assert base["turns"] >= 200
    assert base["sessions"] >= 30
    assert 40 <= deep["turns"] <= 60
    assert deep["expect_model"] <= 60
    assert deep["categories"] >= 8
    assert {session["id"] for session in build_suite()}.isdisjoint(session["id"] for session in deep_suite())


def test_wuhan_cod_passes_and_wrong_freight_fails():
    expect = _expect(style_suite(), "style-ship", "寄到武汉呢")
    assert evaluate_turn(_draft("武汉到付。"), expect) == []
    assert evaluate_turn(_draft("其他城市到付。"), expect) == []
    assert evaluate_turn(_draft("武汉12元。"), expect)
    assert evaluate_turn(_draft("武汉包邮。"), expect)


def test_arrival_question_does_not_reuse_work_time(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.delenv("KEFU_MODEL_MODE", raising=False)
    reset_runtime_state()
    arrival = handle_live_message(
        cookie_id="suite", chat_id="print", sender_id="b", sender_name="b",
        text="打印件能退吗，多久到手", item_id="sim-print",
    )
    assert arrival["status"] == "handoff"
    assert "五天" not in arrival["buyer_visible_draft"]
    assert "到手" not in arrival["buyer_visible_draft"]
    assert "收到" in arrival["buyer_visible_draft"]
    assert "退款" in arrival["buyer_visible_draft"]
    work = handle_live_message(
        cookie_id="suite", chat_id="print-work", sender_id="b", sender_name="b",
        text="不是问多久做完，我问多久收到", item_id="sim-print",
    )
    assert "五天" not in work["buyer_visible_draft"]
    assert "工期" not in work["buyer_visible_draft"]
    done = handle_live_message(
        cookie_id="suite", chat_id="print-done", sender_id="b", sender_name="b",
        text="打印件多久做完", item_id="sim-print",
    )
    assert done["buyer_visible_draft"] == "工期五天。"
    repair = handle_live_message(
        cookie_id="suite", chat_id="repair", sender_id="b", sender_name="b",
        text="把换屏幕的情况和价格一起说", item_id="sim-repair",
    )
    assert "电池另计" in repair["buyer_visible_draft"]
    assert "工期当天" in repair["buyer_visible_draft"]
    assert "在售" not in repair["buyer_visible_draft"]


def test_bad_candidates_are_guard_tests_not_model_quality(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("KEFU_MODEL_MODE", "openai")
    monkeypatch.setenv("KEFU_SUITE_TRACE", "1")

    class Scripted:
        def __init__(self, reply: str):
            self.reply = reply

        def complete(self, messages):
            return self.reply

    class Timeout:
        def complete(self, messages):
            raise ModelCallError("timeout")

    class Empty:
        def complete(self, messages):
            return ""

    reset_runtime_state()
    swapped = handle_live_message(
        cookie_id="suite", chat_id="swap", sender_id="b", sender_name="b",
        text="打印件多久做完，能退吗", item_id="sim-print",
        model_client=Scripted("退款还不确定，五天到手。"),
    )
    assert swapped["model_rejected"] is True
    assert "invented_arrival" in swapped["reject_reasons"] or "dropped_timeline_kind" in swapped["reject_reasons"]
    assert "工期" in swapped["buyer_visible_draft"]
    assert "到手" not in swapped["buyer_visible_draft"]
    assert swapped["model_adopted"] is False

    reset_runtime_state()
    missing_fee = handle_live_message(
        cookie_id="suite", chat_id="fee", sender_id="b", sender_name="b",
        text="把换屏幕的情况和价格一起说", item_id="sim-repair",
        model_client=Scripted("80元，只换屏幕，到店维修，当天。"),
    )
    assert "omitted_addon" in missing_fee["reject_reasons"]
    assert "电池另计" in missing_fee["buyer_visible_draft"]

    reset_runtime_state()
    handle_live_message(
        cookie_id="suite", chat_id="stock", sender_id="b", sender_name="b",
        text="外套还在吗", item_id="sim-jacket", model_client=Scripted("在的。"),
    )
    repeated = handle_live_message(
        cookie_id="suite", chat_id="stock", sender_id="b", sender_name="b",
        text="把外套的情况和价格一起说", item_id=None,
        model_client=Scripted("120元包邮，L码，在售。"),
    )
    assert "repeated_stock" in repeated["reject_reasons"]
    assert "在售" not in repeated["buyer_visible_draft"]
    assert "L码" in repeated["buyer_visible_draft"]

    reset_runtime_state()
    timed = handle_live_message(
        cookie_id="suite", chat_id="timeout", sender_id="b", sender_name="b",
        text="打印件多久做完", item_id="sim-print", model_client=Timeout(),
    )
    assert timed["model_error"] == "timeout"
    assert timed["model_invoked"] is False
    assert timed["buyer_visible_draft"] == "工期五天。"

    reset_runtime_state()
    blank = handle_live_message(
        cookie_id="suite", chat_id="blank", sender_id="b", sender_name="b",
        text="打印件多久做完", item_id="sim-print", model_client=Empty(),
    )
    assert blank["model_rejected"] is True
    assert blank["buyer_visible_draft"] == "工期五天。"

    reset_runtime_state()
    first = handle_live_message(
        cookie_id="suite", chat_id="dup", sender_id="b", sender_name="b",
        text="外套现在卖多少", item_id="sim-jacket", model_client=Scripted("120元包邮。"),
        message_id="same-message",
    )
    second = handle_live_message(
        cookie_id="suite", chat_id="dup", sender_id="b", sender_name="b",
        text="外套现在卖多少", item_id="sim-jacket", model_client=Scripted("不该再叫模型"),
        message_id="same-message",
    )
    assert second["duplicate"] is True
    assert second["model_invoked"] is False
    assert second["buyer_visible_draft"] == first["buyer_visible_draft"]


def test_close_suite_and_replay_does_not_inflate_rejections(tmp_path, monkeypatch):
    from kefu_offline.fixtures.sim_logic_suite import close_suite

    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("KEFU_MODEL_MODE", "openai")
    monkeypatch.delenv("XIANYU_ALLOW_SEND", raising=False)
    counts = suite_counts(close_suite())
    assert counts["turns"] == 6
    assert counts["expect_model"] == 5
    assert counts["expect_rule"] == 1
    summary = run_suite(
        close_suite(),
        model_client=EchoModel(),
        max_model_calls=10,
        timeout_budget_s=120,
        checkpoint=tmp_path / "close.jsonl",
    )
    assert summary["failed"] == 0, json.dumps([row for row in summary["results"] if not row.get("ok")], ensure_ascii=False)
    assert summary["model_invoked"] == 5
    assert summary["model_rejected"] == 0
    assert summary["inherited_guard"] == 0

    class Pile:
        def complete(self, messages):
            return "80元，只换屏幕，工期当天，到店维修，电池另计。"

    piled = [
        {
            "id": "pile",
            "conversation_id": "chat-pile",
            "category": "维修",
            "turns": [
                {
                    "text": "换屏幕现在卖多少",
                    "item_id": "sim-repair",
                    "message_id": "same-price",
                    "expect": {"contain": ["80元", "电池另计"], "absent": ["工期", "只换屏幕"], "model": True, "status": "pending_review"},
                },
                {
                    "text": "换屏幕现在卖多少",
                    "item_id": "sim-repair",
                    "message_id": "same-price",
                    "expect": {"contain": ["80元", "电池另计"], "absent": ["工期"], "model": False, "status": "pending_review"},
                },
            ],
        }
    ]
    replay = run_suite(piled, model_client=Pile(), max_model_calls=5, checkpoint=tmp_path / "pile.jsonl")
    assert replay["failed"] == 0, json.dumps([row for row in replay["results"] if not row.get("ok")], ensure_ascii=False)
    assert replay["model_invoked"] == 1
    assert replay["model_rejected"] == 1
    assert replay["inherited_guard"] == 1
    assert replay["guard_blocked"] == 1
    second = replay["results"][1]
    assert second["duplicate"] is True
    assert second["model_rejected"] is False
    assert second["reject_source"] == "cached_final"
    assert second["inherited_model_rejected"] is True
    assert "工期" not in second["final_draft"]


def test_deep_suite_with_echo_model(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("KEFU_MODEL_MODE", "openai")
    monkeypatch.delenv("XIANYU_ALLOW_SEND", raising=False)
    summary = run_suite(
        deep_suite(),
        model_client=EchoModel(),
        max_model_calls=60,
        timeout_budget_s=240,
        checkpoint=tmp_path / "deep.jsonl",
    )
    assert summary["failed"] == 0, json.dumps(
        [row for row in summary["results"] if not row.get("ok")],
        ensure_ascii=False,
    )
    assert summary["model_invoked"] == suite_counts(deep_suite())["expect_model"]
    assert summary["model_invoked"] <= 60
    assert summary["send_allowed"] is False
