"""口吻子集。假模型和脚本候选都不是 Mac 网关实测。"""

import json

from kefu_offline.fixtures.sim_logic_suite import style_suite, write_catalog
from kefu_offline.live import handle_live_message, note_seller_fact, reset_runtime_state
from kefu_offline.suite_runner import EchoModel, run_suite


def test_style_subset_shape_is_separate_from_the_204():
    from kefu_offline.fixtures.sim_logic_suite import build_suite, suite_counts

    base = suite_counts(build_suite())
    extra = suite_counts(style_suite())
    assert base["turns"] >= 200
    assert base["sessions"] >= 30
    assert extra["sessions"] >= 5
    assert extra["categories"] >= 5
    assert {session["id"] for session in build_suite()}.isdisjoint({session["id"] for session in style_suite()})


def test_style_subset_with_echo_model(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.setenv("KEFU_MODEL_MODE", "openai")
    monkeypatch.delenv("XIANYU_ALLOW_SEND", raising=False)
    summary = run_suite(style_suite(), model_client=EchoModel(), max_model_calls=20, checkpoint=tmp_path / "style.jsonl")
    assert summary["failed"] == 0, json.dumps([row for row in summary["results"] if not row.get("ok")], ensure_ascii=False)
    assert summary["model_invoked"] == summary["turns"]
    saved = (tmp_path / "style.jsonl").read_text(encoding="utf-8")
    assert "成色没确认" not in saved.split("把桌子的情况和价格一起说")[1].split("\n", 1)[0]


def test_rule_drafts_for_overview_identity_followup_and_city(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.yml"
    write_catalog(catalog)
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(catalog))
    monkeypatch.setenv("KEFU_REVIEW_PATH", str(tmp_path / "reviews.jsonl"))
    monkeypatch.delenv("KEFU_MODEL_MODE", raising=False)
    reset_runtime_state()
    jacket_price = handle_live_message(
        cookie_id="suite", chat_id="jacket", sender_id="b", sender_name="b",
        text="外套现在卖多少", item_id="sim-jacket",
    )
    jacket_spec = handle_live_message(
        cookie_id="suite", chat_id="jacket", sender_id="b", sender_name="b",
        text="外套规格是什么", item_id="sim-jacket",
    )
    jacket_again = handle_live_message(
        cookie_id="suite", chat_id="jacket", sender_id="b", sender_name="b",
        text="还是那个价吗", item_id=None,
    )
    assert "成色没确认" not in jacket_price["buyer_visible_draft"]
    assert "L码" in jacket_spec["buyer_visible_draft"]
    assert "120元" not in jacket_spec["buyer_visible_draft"]
    assert "120元" in jacket_again["buyer_visible_draft"]
    assert "成色没确认" not in jacket_again["buyer_visible_draft"]

    reset_runtime_state()
    desk = handle_live_message(
        cookie_id="suite", chat_id="desk", sender_id="b", sender_name="b",
        text="把桌子的情况和价格一起说", item_id="sim-desk",
    )
    asked = handle_live_message(
        cookie_id="suite", chat_id="desk", sender_id="b", sender_name="b",
        text="桌子成色怎么样", item_id=None,
    )
    assert "260元" in desk["buyer_visible_draft"]
    assert "1.2米" in desk["buyer_visible_draft"]
    assert "成色没确认" not in desk["buyer_visible_draft"]
    assert "成色没确认" in asked["buyer_visible_draft"]
    assert "成色一般" not in asked["buyer_visible_draft"]

    reset_runtime_state()
    lens = handle_live_message(
        cookie_id="suite", chat_id="lens", sender_id="b", sender_name="b",
        text="你是AI吗，再便宜点", item_id="sim-lens",
    )
    assert lens["buyer_visible_draft"] == "是自动回复，1500元包邮。"
    assert "我是真人" not in lens["buyer_visible_draft"]

    reset_runtime_state()
    note_seller_fact("sim-fridge", pickup_text=None, shipping_detail="南京运费12元，北京运费15元，其他城市到付")
    beijing = handle_live_message(
        cookie_id="suite", chat_id="ship", sender_id="b", sender_name="b",
        text="寄到北京多少钱", item_id="sim-fridge",
    )
    wuhan = handle_live_message(
        cookie_id="suite", chat_id="ship", sender_id="b", sender_name="b",
        text="寄到武汉呢", item_id=None,
    )
    assert "北京运费15元" in beijing["buyer_visible_draft"]
    assert "400元" in beijing["buyer_visible_draft"]
    assert "包邮" not in beijing["buyer_visible_draft"]
    assert wuhan["buyer_visible_draft"] == "其他城市到付。"
    assert "12元" not in wuhan["buyer_visible_draft"]
    assert "15元" not in wuhan["buyer_visible_draft"]
    from pathlib import Path
    assert "杭州" not in Path("kefu_offline/engine.py").read_text(encoding="utf-8")


def test_bad_style_candidates_fall_back_without_losing_facts(tmp_path, monkeypatch):
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

    reset_runtime_state()
    listed = handle_live_message(
        cookie_id="suite", chat_id="desk-bad", sender_id="b", sender_name="b",
        text="把桌子的情况和价格一起说", item_id="sim-desk",
        model_client=Scripted("260元，成色没确认。"),
    )
    assert listed["model_candidate"] == "260元，成色没确认。"
    assert "unsolicited_condition" in listed["reject_reasons"]
    assert "成色没确认" not in listed["buyer_visible_draft"]
    assert "1.2米" in listed["buyer_visible_draft"]

    reset_runtime_state()
    missing = handle_live_message(
        cookie_id="suite", chat_id="desk-ask", sender_id="b", sender_name="b",
        text="桌子成色怎么样", item_id="sim-desk",
        model_client=Scripted("桌子还在。"),
    )
    assert "omitted_condition" in missing["reject_reasons"]
    assert "成色没确认" in missing["buyer_visible_draft"]

    reset_runtime_state()
    stiff = handle_live_message(
        cookie_id="suite", chat_id="lens-stiff", sender_id="b", sender_name="b",
        text="你是AI吗，再便宜点", item_id="sim-lens",
        model_client=Scripted("是自动回复。1500元包邮。"),
    )
    assert stiff["model_candidate"] == "是自动回复。1500元包邮。"
    assert "stiff_identity" in stiff["reject_reasons"]
    assert stiff["buyer_visible_draft"] == "是自动回复，1500元包邮。"

    reset_runtime_state()
    handle_live_message(
        cookie_id="suite", chat_id="jacket-follow", sender_id="b", sender_name="b",
        text="外套现在卖多少", item_id="sim-jacket", model_client=Scripted("120元包邮。"),
    )
    repeated = handle_live_message(
        cookie_id="suite", chat_id="jacket-follow", sender_id="b", sender_name="b",
        text="外套规格是什么", item_id=None, model_client=Scripted("L码，120元包邮。"),
    )
    assert "repeated_price" in repeated["reject_reasons"]
    assert repeated["buyer_visible_draft"] == "L码。"
    assert "120元" not in repeated["buyer_visible_draft"]

    reset_runtime_state()
    note_seller_fact("sim-fridge", pickup_text=None, shipping_detail="南京运费12元，北京运费15元，其他城市到付")
    invented = handle_live_message(
        cookie_id="suite", chat_id="city", sender_id="b", sender_name="b",
        text="寄到武汉呢", item_id="sim-fridge", model_client=Scripted("武汉12元，包邮。"),
    )
    assert invented["model_rejected"] is True
    assert invented["buyer_visible_draft"] == "其他城市到付。"
    assert "12元" not in invented["buyer_visible_draft"]
    assert "包邮" not in invented["buyer_visible_draft"]
