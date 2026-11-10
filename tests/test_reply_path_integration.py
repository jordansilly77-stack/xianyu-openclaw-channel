"""走 XianyuLive.handle_message。传输层用假 WebSocket，不连接闲鱼。"""

import asyncio
import base64
import json
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="kefu-reply-"))
os.environ["DB_PATH"] = str(_TMP / "xianyu.db")
os.environ["KEFU_REVIEW_PATH"] = str(_TMP / "reviews.jsonl")
os.environ["KEFU_CATALOG_PATH"] = str(_TMP / "catalog.yml")
os.environ["KEFU_MODEL_MODE"] = "rules"
os.environ.pop("XIANYU_ALLOW_SEND", None)

_TMP.joinpath("catalog.yml").write_text(
    """
items:
  - item_id: sim-live-001
    title: 集成测试商品
    kind: goods
    match_terms: []
    listed_price_yuan: 15
    shipping: 包邮
    scope_text: 集成测试范围
    timeline_text: null
    model_text: null
    condition_text: null
    refund_policy: null
    description: 仅用于集成测试。
    floor_price_yuan: null
""".strip(),
    encoding="utf-8",
)

from XianyuAutoAsync import XianyuLive  # noqa: E402
from kefu_offline.review_store import ReviewStore  # noqa: E402


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)


def _packet(message):
    raw = base64.b64encode(json.dumps(message, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return {
        "headers": {"mid": "m1", "sid": "s1"},
        "body": {"syncPushPackage": {"data": [{"data": raw}]}},
    }


def _chat(content, item_id="sim-live-001", wrapped=False):
    body = {
        "10": {
            "senderUserId": "900000000001",
            "senderNick": "模拟买家",
            "reminderContent": content,
            "reminderUrl": f"fleamarket://message_chat?itemId={item_id}&peerUserId=900000000001"
            if item_id
            else "",
        },
        "2": "live-int@goofish",
        "5": 1700000000000,
    }
    return {"1": [body] if wrapped else body, "3": {}}


async def _run(message):
    live = XianyuLive(cookies_str="unb=test-seller", cookie_id="preview-account")
    live.message_debounce_delay = 0
    socket = FakeSocket()
    await live.handle_message(_packet(message), socket)
    await asyncio.sleep(0.2)
    return socket, ReviewStore().list_records()


def test_handle_message_matches_item_and_does_not_send():
    socket, reviews = asyncio.run(_run(_chat("多少钱，包含什么")))
    assert reviews
    latest = reviews[-1]
    assert latest["matched_item_id"] == "sim-live-001"
    assert "15元" in latest["buyer_visible_draft"]
    assert "集成测试范围" in latest["buyer_visible_draft"]
    assert latest["send_allowed"] is False
    assert all("MessageSend" not in payload for payload in socket.sent)


def test_list_message_and_unknown_item_are_not_dropped():
    _socket, listed = asyncio.run(_run(_chat("包含什么", wrapped=True)))
    assert listed[-1]["matched_item_id"] == "sim-live-001"
    assert "集成测试范围" in listed[-1]["buyer_visible_draft"]

    socket, reviews = asyncio.run(
        _run(
            {
                "1": {
                    "10": {
                        "senderUserId": "900000000001",
                        "senderNick": "模拟买家",
                        "reminderContent": "帮我看 999000111222",
                        "reminderUrl": "",
                    },
                    "2": "unknown-int@goofish",
                    "5": 1700000000000,
                },
                "3": {},
            }
        )
    )
    assert reviews[-1]["reason"] == "unknown_item"
    assert "999000111222" not in reviews[-1]["buyer_visible_draft"]
    assert reviews[-1]["matched_item_id"] is None
    assert all("MessageSend" not in payload for payload in socket.sent)


def test_database_price_answers_without_catalog_entry(monkeypatch):
    monkeypatch.setenv("KEFU_CATALOG_PATH", str(_TMP / "empty.yml"))
    _TMP.joinpath("empty.yml").write_text("items: []\n", encoding="utf-8")
    from db_manager import db_manager

    db_manager.save_item_info(
        "preview-account",
        "db-item-001",
        {"title": "库里的测试商品", "price": "28", "description": "来自测试库"},
    )
    _socket, reviews = asyncio.run(_run(_chat("多少钱", item_id="db-item-001")))
    assert reviews[-1]["matched_item_id"] == "db-item-001"
    assert "28元" in reviews[-1]["buyer_visible_draft"]
    assert "库里的测试商品" in reviews[-1]["buyer_visible_draft"]
