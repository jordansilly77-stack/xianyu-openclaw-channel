"""对照当前仓库里的商品识别代码，不启动闲鱼连接。"""

import re
from pathlib import Path
from types import SimpleNamespace

from kefu_offline.engine import trusted_item_id_from_wire


ROOT = Path(__file__).resolve().parents[1]


def _load_upstream_extractor():
    source = (ROOT / "XianyuAutoAsync.py").read_text(encoding="utf-8")
    start = source.index("    def extract_item_id_from_message")
    end = source.index("\n    def debug_message_structure")
    method = source[start:end]
    dedented = "\n".join(
        line[4:] if line.startswith("    ") else line for line in method.splitlines()
    )
    namespace = {
        "re": re,
        "logger": SimpleNamespace(
            info=lambda *_a, **_k: None,
            warning=lambda *_a, **_k: None,
            error=lambda *_a, **_k: None,
        ),
    }
    exec(dedented, namespace)  # noqa: S102 - 执行本仓库里的原函数，便于对照
    return namespace["extract_item_id_from_message"]


class _Dummy:
    cookie_id = "example"

    def _safe_str(self, exc):
        return str(exc)


def _sample_message():
    return {
        "1": {
            "10": {
                "senderUserId": "2207836320265",
                "reminderContent": "看下商品 999000111222",
                "reminderUrl": "fleamarket://message_chat?itemId=100200300400&peerUserId=2207836320265",
            },
            "2": "555666777888@goofish",
            "5": 1700000000000,
        },
        "3": {},
    }


def test_extractor_uses_item_url_not_sender_id():
    extract = _load_upstream_extractor()
    message = _sample_message()

    assert extract(_Dummy(), message) == "100200300400"
    assert trusted_item_id_from_wire(message) == "100200300400"


def test_extractor_reads_list_wrapped_item_url():
    extract = _load_upstream_extractor()
    message = _sample_message()
    wrapped = {"1": [message["1"]], "3": {}}

    assert extract(_Dummy(), wrapped) == "100200300400"
    assert trusted_item_id_from_wire(wrapped) == "100200300400"


def test_live_handler_keeps_unknown_items_for_review():
    source = (ROOT / "XianyuAutoAsync.py").read_text(encoding="utf-8")
    start = source.index("    async def handle_message")
    end = source.index("\n    async def ", start + 10)
    handler = source[start:end]

    assert handler.index("normalize_wire_message") < handler.index(
        "消息格式错误：缺少必要的字段结构"
    )
    assert "auto_{user_id}" not in handler
    assert "needsHuman" in handler
    assert handler.index("消息格式错误：缺少必要的字段结构") < handler.index(
        "bridge_queue.publish"
    )

    chat_check = source[
        source.index("    def is_chat_message") : source.index("    def is_sync_package")
    ]
    assert "isinstance(msg_1, list)" in chat_check

    inbound = (ROOT / "openclaw-plugin" / "src" / "inbound-handler.ts").read_text(
        encoding="utf-8"
    )
    assert "buyerVisibleBody" in inbound
    assert "deliveryAllowsSend" in inbound
    assert "ItemId: data.itemId" in inbound

    reply = source[source.index("    async def get_ai_reply") : source.index("    def _parse_price")]
    assert "商品信息获取失败" not in reply
    assert "不编造商品" in reply

    config = (ROOT / "global_config.yml").read_text(encoding="utf-8")
    assert "delivery: preview" in config
    assert "可以直接申请退款" in config

    assert not (ROOT / "safari_token.py").exists()
    skills = sorted((ROOT / "openclaw-plugin" / "skills").glob("*/SKILL.md"))
    assert ROOT / "openclaw-plugin" / "skills" / "xianyu-product" / "SKILL.md" in skills
    assert ROOT / "openclaw-plugin" / "skills" / "xianyu-kefu" / "SKILL.md" in skills
