"""云端用假模型跑多轮套件。不是用户 Mac 上的真实模型验收。"""

import json
from pathlib import Path

from kefu_offline.fixtures.sim_logic_suite import build_suite, suite_counts, write_catalog
from kefu_offline.suite_runner import EchoModel, evaluate_turn, run_suite


def test_stock_questions_do_not_require_the_word_zaishou():
    from kefu_offline.fixtures.sim_logic_suite import build_suite

    for session in build_suite():
        for index, turn in enumerate(session["turns"], start=1):
            if "还在吗" not in turn["text"]:
                continue
            expect = turn["expect"]
            if expect.get("availability") == "sold":
                assert "在售" not in (expect.get("contain") or []), session["id"]
                continue
            if expect.get("availability") != "in_stock":
                continue
            assert "在售" not in (expect.get("contain") or []), f"{session['id']}-{index}"
            assert evaluate_turn(
                {
                    "status": "pending_review",
                    "buyer_visible_draft": "在的。",
                    "model_invoked": True,
                    "send_allowed": False,
                    "transport_send": False,
                },
                expect,
            ) == [], f"{session['id']}-{index} should accept 在的"


def test_suite_shape_is_large_enough():
    counts = suite_counts()
    assert counts["sessions"] >= 30
    assert counts["turns"] >= 200
    assert counts["categories"] >= 10
    assert counts["expect_model"] >= 120
    assert counts["expect_rule"] > 0


def test_suite_with_fake_model(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("KEFU_MODEL_MODE", "openai")
    monkeypatch.delenv("XIANYU_ALLOW_SEND", raising=False)
    summary = run_suite(
        build_suite(),
        model_client=EchoModel(),
        max_model_calls=180,
        checkpoint=tmp_path / "suite.jsonl",
    )
    assert summary["failed"] == 0, _sample(summary)
    assert summary["turns"] >= 200
    assert summary["sessions"] >= 30
    assert summary["model_invoked"] >= 120
    assert summary["send_allowed"] is False
    saved = (tmp_path / "reviews.jsonl").read_text(encoding="utf-8").lower()
    assert "bearer " not in saved
    assert "api_key" not in saved


def test_fake_candidates_for_stock_total_condition_and_bargain(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("KEFU_MODEL_MODE", "openai")
    monkeypatch.setenv("KEFU_SUITE_TRACE", "1")
    monkeypatch.delenv("XIANYU_ALLOW_SEND", raising=False)
    from kefu_offline.live import handle_live_message, reset_runtime_state

    class Scripted:
        def __init__(self, reply: str):
            self.reply = reply

        def complete(self, messages):
            return self.reply

    reset_runtime_state()
    instock = handle_live_message(
        cookie_id="suite", chat_id="code", sender_id="b", sender_name="b",
        text="激活码还在吗", item_id="sim-code", model_client=Scripted("在的。"),
    )
    assert instock["model_adopted"] is True
    assert evaluate_turn(instock, {"model": True, "status": "pending_review", "availability": "in_stock", "absent": ["卖出"]}) == []

    reset_runtime_state()
    from kefu_offline.live import note_seller_fact
    note_seller_fact("sim-jacket", stock_text="已售出")
    sold = handle_live_message(
        cookie_id="suite", chat_id="sold", sender_id="b", sender_name="b",
        text="外套还在吗", item_id="sim-jacket", model_client=Scripted("在的。"),
    )
    assert sold["model_rejected"] is True
    assert "sold_said_available" in (sold.get("reject_reasons") or [])
    assert evaluate_turn(sold, {"model": True, "availability": "sold", "contain": ["卖出"], "absent": ["在的"]}) == []

    reset_runtime_state()
    good_total = handle_live_message(
        cookie_id="suite", chat_id="books", sender_id="b", sender_name="b",
        text="两套一共多少", item_id="sim-books", model_client=Scripted("两套90元。"),
    )
    assert good_total["model_adopted"] is True
    assert "90元" in good_total["buyer_visible_draft"]

    reset_runtime_state()
    bad_total = handle_live_message(
        cookie_id="suite", chat_id="books2", sender_id="b", sender_name="b",
        text="两套一共多少", item_id="sim-books", model_client=Scripted("一共80元。"),
    )
    assert bad_total["model_rejected"] is True
    assert bad_total["model_candidate"] == "一共80元。"
    assert "90元" in bad_total["buyer_visible_draft"]
    assert bad_total["model_adopted"] is False

    reset_runtime_state()
    fabricated = handle_live_message(
        cookie_id="suite", chat_id="fridge", sender_id="b", sender_name="b",
        text="冰箱成色怎么样", item_id="sim-fridge", model_client=Scripted("制冷正常，成色一般。"),
    )
    assert fabricated["model_rejected"] is True
    assert "成色没确认" in fabricated["buyer_visible_draft"]
    assert "成色一般" not in fabricated["buyer_visible_draft"]
    assert "制冷正常" not in fabricated["buyer_visible_draft"]

    reset_runtime_state()
    bargain = handle_live_message(
        cookie_id="suite", chat_id="lens", sender_id="b", sender_name="b",
        text="你是AI吗，再便宜点", item_id="sim-lens", model_client=Scripted("是自动回复。1500元不行，现价包邮。"),
    )
    assert bargain["model_rejected"] is True
    assert "1500元不行" not in bargain["buyer_visible_draft"]
    assert "1500元" in bargain["buyer_visible_draft"]
    assert "是自动回复" in bargain["buyer_visible_draft"]


def test_sold_reply_that_says_available_is_blocked(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("KEFU_MODEL_MODE", "openai")
    monkeypatch.setenv("KEFU_SUITE_TRACE", "1")
    from kefu_offline.live import handle_live_message, note_seller_fact, reset_runtime_state

    class Scripted:
        def complete(self, messages):
            return "在的。"

    reset_runtime_state()
    note_seller_fact("sim-jacket", stock_text="已售出")
    sold = handle_live_message(
        cookie_id="suite", chat_id="sold-bad", sender_id="b", sender_name="b",
        text="外套还在吗", item_id="sim-jacket", model_client=Scripted(),
    )
    assert sold["model_candidate"] == "在的。"
    assert "sold_said_available" in sold["reject_reasons"]
    assert sold["model_adopted"] is False
    assert evaluate_turn(sold, {"model": True, "availability": "sold", "contain": ["卖出"], "absent": ["在的"]}) == []


def test_assertions_catch_a_wrong_price():
    failures = evaluate_turn(
        {
            "status": "pending_review",
            "reason": "listed_price",
            "buyer_visible_draft": "700元可以。",
            "model_invoked": True,
            "send_allowed": False,
            "transport_send": False,
        },
        {"status": "pending_review", "model": True, "contain": ["880元"], "absent": ["700元可以"], "negation": True},
    )
    assert failures


def _sample(summary: dict) -> str:
    bad = [row for row in summary["results"] if not row.get("ok")][:8]
    return json.dumps(bad, ensure_ascii=False, indent=2)
