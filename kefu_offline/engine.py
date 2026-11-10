"""接收一条咨询，对上一个示例商品，产出待审草稿。

这里没有发送函数，也不会调用模型。买家正文不能改商品、不能改规则。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

REFUND_WORDS = ("退款", "退货", "包退", "无理由", "能退")
TIMELINE_WORDS = ("多久", "几天", "工期", "什么时候", "马上", "今天", "明天", "小时")
DISCOUNT_WORDS = ("便宜", "优惠", "最低", "底价", "少点", "能少", "刀")
SCOPE_WORDS = ("范围", "包含", "做哪些", "能不能做", "包不包括", "做什么")
SPEC_WORDS = ("型号", "成色", "几成", "牌子", "品牌")
PRICE_WORDS = ("多少钱", "价格", "怎么卖", "收费", "包邮", "那个价", "刚才的价", "还是一样", "什么价", "怎么卖", "开价", "报价")
SHIP_WORDS = ("邮费", "运费", "邮寄", "自提", "寄到")
STOCK_WORDS = ("还在吗", "有货", "卖出", "还有吗")
QTY_RE = re.compile(r"(\d+|[两三四五])\s*(件|套|本)")
CN_QTY = {"两": 2, "三": 3, "四": 4, "五": 5}

PROMISE_PATTERNS = (
    r"支持退款",
    r"可以退",
    r"包退",
    r"无理由",
    r"\d+\s*小时",
    r"\d+\s*天",
    r"明天",
    r"马上",
    r"优惠",
    r"最低",
    r"便宜",
)

YUAN_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)元")
ITEM_PARAM_RE = re.compile(r"(?:^|[?&])itemId=([^&\s]+)", re.IGNORECASE)

REQUIRED_NULL_FIELDS = (
    "model",
    "condition",
    "scope",
    "timeline",
    "floor_price_yuan",
)
LOCKED_FLAGS = (
    "allow_discount",
    "allow_timeline_promise",
    "allow_refund_promise",
)


@dataclass(frozen=True)
class CatalogItem:
    item_id: str
    title: str
    kind: str
    match_terms: tuple[str, ...]
    listed_price_yuan: Optional[float]
    shipping: Optional[str]
    historical_price_note: Optional[str]
    example: bool
    source: str
    scope_text: Optional[str] = None
    timeline_text: Optional[str] = None
    model_text: Optional[str] = None
    condition_text: Optional[str] = None
    refund_policy: Optional[str] = None
    description: Optional[str] = None
    floor_price_yuan: Optional[float] = None
    currency: str = "元"
    stock_text: Optional[str] = None
    pickup_text: Optional[str] = None
    specs_text: Optional[str] = None
    accessories_text: Optional[str] = None
    bundle_text: Optional[str] = None
    shipping_detail: Optional[str] = None
    prerequisites_text: Optional[str] = None
    addons_text: Optional[str] = None
    function_text: Optional[str] = None


@dataclass(frozen=True)
class Incoming:
    case_id: str
    conversation_id: str
    sender_id: str
    text: str
    trusted_item_id: Optional[str]


@dataclass(frozen=True)
class Decision:
    case_id: str
    status: str
    reason: str
    matched_item_id: Optional[str]
    buyer_visible_draft: str
    audit_note: str
    send_allowed: bool
    example: bool
    generator: str
    model_invoked: bool
    mock_draft_rejected: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Catalog:
    def __init__(self, items: list[CatalogItem], catalog_id: str, disclaimer: str):
        self.items = items
        self.catalog_id = catalog_id
        self.disclaimer = disclaimer
        self._by_id = {item.item_id: item for item in items}

    def by_id(self, item_id: Optional[str]) -> Optional[CatalogItem]:
        if not item_id:
            return None
        return self._by_id.get(item_id)


def load_catalog(path: Optional[Path] = None) -> Catalog:
    catalog_path = Path(path) if path else FIXTURE_DIR / "example_catalog.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    items: list[CatalogItem] = []
    seen: set[str] = set()
    for raw in payload.get("items", []):
        items.append(_parse_item(raw, seen))
    if not items:
        raise ValueError("示例目录是空的")
    return Catalog(
        items=items,
        catalog_id=str(payload.get("catalog_id") or ""),
        disclaimer=str(payload.get("disclaimer") or ""),
    )


def _parse_item(raw: dict, seen: set[str]) -> CatalogItem:
    if raw.get("example") is not True or raw.get("source") != "simulated-example":
        raise ValueError(f"{raw.get('item_id')} 必须标明 simulated-example")
    for field in REQUIRED_NULL_FIELDS:
        if raw.get(field) is not None:
            raise ValueError(f"{raw.get('item_id')} 的 {field} 不能编造，必须是 null")
    for flag in LOCKED_FLAGS:
        if raw.get(flag) is not False:
            raise ValueError(f"{raw.get('item_id')} 不能打开 {flag}")
    item_id = str(raw.get("item_id") or "").strip()
    title = str(raw.get("title") or "").strip()
    kind = raw.get("kind")
    if not item_id or not title or kind not in {"service", "goods"}:
        raise ValueError("目录条目缺少 item_id、title 或 kind")
    if item_id in seen:
        raise ValueError(f"重复的 item_id: {item_id}")
    seen.add(item_id)
    terms = raw.get("match_terms")
    if not isinstance(terms, list) or not terms or not all(isinstance(term, str) and term.strip() for term in terms):
        raise ValueError(f"{item_id} 缺少 match_terms")
    price = raw.get("listed_price_yuan")
    shipping = raw.get("shipping")
    if kind == "service" and (price is not None or shipping is not None):
        raise ValueError(f"{item_id} 是服务，不能写死标价或运费")
    if price is not None and not isinstance(price, (int, float)):
        raise ValueError(f"{item_id} 的标价不是数字")
    if shipping not in (None, "包邮"):
        raise ValueError(f"{item_id} 的运费只能是 null 或已陈述的包邮")
    note = raw.get("historical_price_note")
    if note is not None and not isinstance(note, str):
        raise ValueError(f"{item_id} 的 historical_price_note 必须是字符串或 null")
    return CatalogItem(
        item_id=item_id,
        title=title,
        kind=kind,
        match_terms=tuple(term.strip() for term in terms),
        listed_price_yuan=float(price) if price is not None else None,
        shipping=shipping,
        historical_price_note=note,
        example=True,
        source="simulated-example",
    )


def normalize_wire_message(message: Any) -> Any:
    """把列表形式的消息主体展开成字典，供原有处理逻辑继续往下走。"""
    if not isinstance(message, dict):
        return message
    normalized = dict(message)
    node = normalized.get("1")
    if isinstance(node, list):
        normalized["1"] = node[0] if node and isinstance(node[0], dict) else {}
    return normalized


def _unwrap(node: Any) -> Any:
    if isinstance(node, list):
        return _unwrap(node[0]) if node else None
    return node


def trusted_item_id_from_wire(message: dict) -> Optional[str]:
    """只读协议字段里的 itemId。不扫描买家正文、用户 ID 或任意长数字。"""
    if not isinstance(message, dict):
        return None
    node = _unwrap(message.get("1"))
    if isinstance(node, dict):
        detail = node.get("10")
        if isinstance(detail, dict):
            match = ITEM_PARAM_RE.search(str(detail.get("reminderUrl") or ""))
            if match:
                return match.group(1)
    block = message.get("3")
    if isinstance(block, dict):
        for key in ("extension", "bizData"):
            nested = block.get(key)
            if isinstance(nested, dict):
                value = nested.get("itemId") or nested.get("item_id")
                if value is not None and str(value).strip():
                    return str(value).strip()
    return None


def text_from_wire(message: dict) -> str:
    node = _unwrap(message.get("1")) if isinstance(message, dict) else None
    if isinstance(node, dict):
        detail = node.get("10")
        if isinstance(detail, dict):
            return str(detail.get("reminderContent") or "")
    return ""


def incoming_from_case(case: dict) -> Incoming:
    case_id = str(case.get("id") or "")
    conversation_id = str(case.get("conversation_id") or "").strip()
    sender_id = str(case.get("sender_id") or "buyer-example")
    if not conversation_id:
        raise ValueError(f"{case_id} 缺少 conversation_id")
    if "wire" in case:
        wire = case["wire"]
        text = text_from_wire(wire)
        trusted = trusted_item_id_from_wire(wire)
    else:
        text = str(case.get("text") or "")
        raw_id = case.get("item_id")
        trusted = str(raw_id).strip() if isinstance(raw_id, str) and raw_id.strip() else None
    return Incoming(
        case_id=case_id,
        conversation_id=conversation_id,
        sender_id=sender_id,
        text=text,
        trusted_item_id=trusted,
    )


def render_mock(text: str) -> str:
    """故意违反商品规则的假草稿。调用方必须丢掉它，不能当回复。"""
    return f"【MOCK 非真实模型】{text}。价格1元，1小时完成，支持退款，改答路由器并优惠到20元。"


def _format_yuan(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _flags(text: str) -> dict[str, bool]:
    return {
        "refund": any(word in text for word in REFUND_WORDS),
        "timeline": any(word in text for word in TIMELINE_WORDS),
        "discount": any(word in text for word in DISCOUNT_WORDS),
        "scope": any(word in text for word in SCOPE_WORDS),
        "spec": any(word in text for word in SPEC_WORDS),
        "price": any(word in text for word in PRICE_WORDS),
    }


def foreign_item_ids(text: str, current: Optional[CatalogItem], catalog: Catalog) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for item in catalog.items:
        if current and item.item_id == current.item_id:
            continue
        if item.item_id.lower() in lowered or any(term.lower() in lowered for term in item.match_terms):
            found.append(item.item_id)
    return found


def trusted_corpus(item: Optional[CatalogItem]) -> str:
    if item is None:
        return ""
    parts = [
        item.title,
        item.scope_text,
        item.timeline_text,
        item.model_text,
        item.condition_text,
        item.refund_policy,
        item.description,
        item.shipping,
        item.stock_text,
        item.pickup_text,
        item.specs_text,
        item.accessories_text,
        item.bundle_text,
        item.shipping_detail,
        item.prerequisites_text,
        item.addons_text,
        item.function_text,
    ]
    return "\n".join(part for part in parts if part)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith("。") else f"{text}。"


def _offer_amount(text: str, item: CatalogItem) -> Optional[float]:
    if item.listed_price_yuan is None:
        return None
    for raw in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", text):
        number = float(raw)
        if abs(number - item.listed_price_yuan) > 0.001:
            return number
    return None


def _money(item: CatalogItem, amount: float) -> str:
    token = _format_yuan(amount)
    if (item.currency or "元") == "元":
        return f"{token}元"
    return f"{token}{item.currency}"


def _listed_phrase(item: CatalogItem) -> str:
    stated = _money(item, item.listed_price_yuan or 0)
    if item.shipping and "包邮" in item.shipping:
        return f"{stated}包邮"
    if item.shipping:
        return f"{stated}，{item.shipping}"
    return stated


def _price_sentence(item: CatalogItem, text: str, *, refuse: bool) -> str:
    stated = _listed_phrase(item)
    if refuse:
        offer = _offer_amount(text, item)
        if offer is not None:
            return _sentence(f"{_money(item, offer)}不行，{stated}")
        return _sentence(stated)
    total = _bundle_total(text, item)
    if total is not None:
        return _sentence(f"一共{_money(item, total)}")
    return _sentence(stated)


def _bundle_total(text: str, item: CatalogItem) -> Optional[float]:
    if item.listed_price_yuan is None or not any(word in text for word in ("一共", "总共", "加起来")):
        return None
    match = QTY_RE.search(text)
    if not match:
        return None
    raw = match.group(1)
    count = CN_QTY.get(raw, int(raw) if raw.isdigit() else 0)
    if count < 2:
        return None
    return item.listed_price_yuan * count


def _has_grade(item: CatalogItem) -> bool:
    text = item.condition_text or ""
    return any(token in text for token in ("新", "成色", "品相"))


def _asks_identity(text: str) -> bool:
    folded = text.lower().replace(" ", "")
    return any(phrase in folded for phrase in ("是不是ai", "你是ai", "是ai吗", "机器人", "真人"))


def _gap_sentence(gaps: list[str]) -> str:
    labels = {
        "refund_unconfirmed": "退款",
        "timeline_unconfirmed": "工期",
        "scope_unconfirmed": "范围",
        "fact_unconfirmed": "型号成色",
        "price_unconfirmed": "价格",
    }
    names = [labels[gap] for gap in gaps if gap in labels]
    if not names:
        return ""
    if len(names) == 1:
        return f"{names[0]}还不确定。"
    if len(names) == 2:
        return f"{names[0]}和{names[1]}都还不确定。"
    return f"{'、'.join(names[:-1])}和{names[-1]}都还不确定。"


def _compose(text: str, item: Optional[CatalogItem], catalog: Catalog) -> tuple[str, str, str, list[str]]:
    """返回 status、reason、买家草稿、内部缺口。买家草稿不写「转人工」。"""
    if item is None:
        if any(word in text for word in PRICE_WORDS) or _conflicting_price_number_text(text):
            return "handoff", "unknown_item", "没对上这件，价格我说不准。", ["unknown_item"]
        return "handoff", "unknown_item", "没对上这件。", ["unknown_item"]
    if item.stock_text == "已售出":
        return "pending_review", "stock_sold", "已经卖出了。", []
    if not text.strip():
        return "handoff", "empty", "你想问什么？", ["empty"]
    if foreign_item_ids(text, item, catalog):
        return "handoff", "cross_item", f"{item.title}这件不跟别的一起答。", ["cross_item"]

    flags = _flags(text)
    parts: list[str] = []
    gaps: list[str] = []
    asked = False
    offer = _offer_amount(text, item) if item.listed_price_yuan is not None else None
    refused_offer = offer is not None
    wants_price = flags["price"] or flags["discount"] or "最低" in text or "底价" in text

    if _asks_identity(text):
        asked = True
        parts.append("是自动回复。")
    if flags["refund"]:
        asked = True
        if item.refund_policy:
            parts.append(_sentence(item.refund_policy))
        else:
            gaps.append("refund_unconfirmed")
    if flags["timeline"]:
        asked = True
        if item.timeline_text:
            parts.append(_sentence(item.timeline_text if str(item.timeline_text).startswith("工期") else f"工期{item.timeline_text}"))
        else:
            gaps.append("timeline_unconfirmed")
    if flags["scope"]:
        asked = True
        if item.scope_text:
            parts.append(_sentence(item.scope_text if "。" in item.scope_text else f"{item.scope_text}"))
        else:
            gaps.append("scope_unconfirmed")
    if any(word in text for word in STOCK_WORDS) and item.stock_text and item.stock_text != "已售出":
        asked = True
        parts.append(_sentence(item.stock_text))
    if any(word in text for word in SHIP_WORDS):
        asked = True
        if item.shipping and "包邮" in item.shipping and (flags["price"] or refused_offer):
            pass
        elif item.shipping and "包邮" in item.shipping:
            parts.append("包邮。")
        elif item.pickup_text:
            parts.append(_sentence(f"不邮寄，{item.pickup_text}"))
        elif item.shipping_detail:
            named = [city for city in ("北京", "上海", "广州", "深圳", "杭州") if city in text]
            if named and named[0] in item.shipping_detail:
                parts.append(_sentence(item.shipping_detail))
            elif named:
                gaps.append("scope_unconfirmed")
            else:
                parts.append("寄到哪？")
        elif item.shipping:
            parts.append(_sentence(item.shipping))
        else:
            gaps.append("scope_unconfirmed")
    if any(word in text for word in ("成色", "新旧", "几成")):
        asked = True
        if _has_grade(item):
            parts.append(_sentence(item.condition_text or ""))
        else:
            parts.append("成色没确认。")
    if any(word in text for word in ("制冷", "功能")) and item.function_text:
        asked = True
        parts.append(_sentence(item.function_text))
    if any(word in text for word in ("配件", "充电器", "前后盖")) and item.accessories_text:
        asked = True
        parts.append(_sentence(item.accessories_text))
    if any(word in text for word in ("几本", "套装")) and item.bundle_text:
        asked = True
        parts.append(_sentence(item.bundle_text))
    if any(word in text for word in ("尺寸", "尺码", "规格", "多大")) and item.specs_text:
        asked = True
        parts.append(_sentence(item.specs_text))
    elif any(word in text for word in ("尺寸", "尺码", "规格", "多大")):
        asked = True
        gaps.append("fact_unconfirmed")
    if any(word in text for word in ("前提", "依赖", "要准备")) and item.prerequisites_text:
        asked = True
        parts.append(_sentence(item.prerequisites_text))
    if any(word in text for word in ("增项", "另加", "电池另")) and item.addons_text:
        asked = True
        parts.append(_sentence(item.addons_text))
    if "密钥" in text or "API_KEY" in text.upper():
        asked = True
        parts.append("密钥不能发。")
    if any(word in text for word in ("型号", "牌子", "品牌")):
        asked = True
        if item.model_text:
            parts.append(_sentence(f"型号{item.model_text}"))
        else:
            gaps.append("fact_unconfirmed")
    if item.listed_price_yuan is None and _conflicting_price_number(text, item):
        asked = True
        gaps.append("price_unconfirmed")
    elif refused_offer or wants_price:
        asked = True
        if item.listed_price_yuan is not None:
            parts.append(_price_sentence(item, text, refuse=refused_offer))
        else:
            gaps.append("price_unconfirmed")
    if gaps:
        parts.append(_gap_sentence(gaps))
    draft = _tight(parts)

    if not asked:
        if item.listed_price_yuan is not None:
            return "pending_review", "ack", f"在，{_price_sentence(item, text, refuse=False)}", []
        return "pending_review", "ack", f"在，{item.title}。", []

    if gaps:
        return "handoff", gaps[0], draft, gaps
    if wants_price or refused_offer:
        reason = "listed_price"
    elif flags["scope"]:
        reason = "scope_quote"
    elif flags["timeline"]:
        reason = "timeline_quote"
    elif flags["spec"]:
        reason = "spec_quote"
    elif flags["refund"]:
        reason = "refund_quote"
    else:
        reason = "ack"
    return "pending_review", reason, draft, []


def _tight(parts: list[str]) -> str:
    cleaned = [part.strip() for part in parts if part and part.strip()]
    if not cleaned:
        return ""
    if cleaned[0] == "是自动回复。":
        rest = "，".join(part.rstrip("。") for part in cleaned[1:])
        return "是自动回复。" + (f"{rest}。" if rest else "")
    body = "，".join(part.rstrip("。") for part in cleaned)
    return body if body.endswith("。") else body + "。"


def _audit(reason: str, generator: str) -> str:
    notes = {
        "ack": "只使用已填写的商品资料。",
        "listed_price": "只复述已填写的标价和运费。",
        "scope_quote": "只复述已填写的范围。",
        "timeline_quote": "只复述已填写的工期。",
        "spec_quote": "只复述已填写的型号或成色。",
        "refund_quote": "只复述已填写的退换说明。",
        "floor_quote": "只复述已填写的底价。",
        "unknown_item": "没有可信商品 ID，正文里的商品名不算匹配。",
        "cross_item": "正文点到了别的商品，仍保持当前绑定。",
        "price_unconfirmed": "没有可确认的成交价或底价。",
        "timeline_unconfirmed": "工期没有记录。",
        "refund_unconfirmed": "没有退款授权。",
        "scope_unconfirmed": "服务或商品范围没有记录。",
        "fact_unconfirmed": "型号和成色没有记录。",
        "empty": "没有可回复的正文。",
    }
    note = notes.get(reason, "不能确认。") + "未发送。"
    if generator == "mock":
        note += " mock 草稿已丢弃，没有调用模型。"
    return note


_DIRECT_REASONS = {"ack", "listed_price", "scope_quote", "timeline_quote", "spec_quote", "refund_quote", "floor_quote"}


def draft_safety_problems(draft: str, decision: Decision, catalog: Catalog, buyer_text: str = "") -> list[str]:
    item = catalog.by_id(decision.matched_item_id)
    allowed_prices: list[float] = []
    allow_shipping = False
    if item and item.listed_price_yuan is not None:
        allowed_prices.append(item.listed_price_yuan)
        allow_shipping = bool(item.shipping and "包邮" in item.shipping)
        total = _bundle_total(buyer_text, item)
        if total is not None:
            allowed_prices.append(total)
    if item and decision.reason == "floor_quote" and item.floor_price_yuan is not None:
        allowed_prices.append(item.floor_price_yuan)
    return text_safety_problems(
        draft,
        allowed_price=allowed_prices[0] if len(allowed_prices) == 1 else None,
        allowed_prices=allowed_prices,
        allow_shipping=allow_shipping,
        trusted_text=trusted_corpus(item),
    )


def text_safety_problems(
    draft: str,
    *,
    allowed_price: Optional[float],
    allow_shipping: bool,
    trusted_text: str = "",
    allowed_prices: Optional[list[float]] = None,
) -> list[str]:
    problems: list[str] = []
    if "MOCK" in draft or "旧标价" in draft:
        problems.append("draft_leaks_internal_note")
    prices = list(allowed_prices or [])
    if allowed_price is not None and not prices:
        prices.append(allowed_price)
    for pattern in PROMISE_PATTERNS:
        for match in re.finditer(pattern, draft):
            if match.group(0) not in trusted_text:
                problems.append(f"promise:{pattern}")
                break
    if "包邮" in draft and not allow_shipping and "包邮" not in trusted_text:
        problems.append("unapproved_shipping")
    for raw in YUAN_RE.findall(draft):
        value = float(raw)
        if any(abs(value - price) <= 0.001 for price in prices):
            continue
        token = _format_yuan(value)
        refusal = f"{token}元不行"
        if refusal in draft and prices:
            remainder = draft.replace(refusal, "", 1)
            if not re.search(rf"(?<!\d){re.escape(token)}元", remainder):
                continue
        problems.append(f"unapproved_price:{raw}")
    return problems


def _conflicting_price_number_text(text: str) -> bool:
    return bool(re.search(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", text))


def _conflicting_price_number(text: str, item: CatalogItem) -> bool:
    numbers = [float(raw) for raw in re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", text)]
    if not numbers:
        return False
    if item.listed_price_yuan is None:
        return True
    return any(abs(number - item.listed_price_yuan) > 0.001 for number in numbers)


def _decide_reason(text: str, item: Optional[CatalogItem], catalog: Catalog) -> str:
    if item is None:
        return "unknown_item"
    if not text.strip():
        return "empty"
    if foreign_item_ids(text, item, catalog):
        return "cross_item"
    flags = _flags(text)
    if flags["refund"]:
        return "refund_quote" if item.refund_policy else "refund_unconfirmed"
    if flags["timeline"]:
        return "timeline_quote" if item.timeline_text else "timeline_unconfirmed"
    if flags["scope"]:
        return "scope_quote" if item.scope_text else "scope_unconfirmed"
    if flags["spec"]:
        return "spec_quote" if (item.model_text or item.condition_text) else "fact_unconfirmed"
    if flags["discount"]:
        return "floor_quote" if item.floor_price_yuan is not None else "price_unconfirmed"
    if _conflicting_price_number(text, item) or (flags["price"] and item.listed_price_yuan is None):
        return "price_unconfirmed"
    if flags["price"] and item.listed_price_yuan is not None:
        return "listed_price"
    return "ack"


class Engine:
    def __init__(self, catalog: Catalog, generator: str = "rules"):
        if generator not in {"rules", "mock"}:
            raise ValueError("generator 只能是 rules 或 mock")
        self.catalog = catalog
        self.generator = generator
        self.bound: dict[str, str] = {}
        self.reviews: list[Decision] = []
        self.send_attempts = 0

    def handle(self, incoming: Incoming) -> Decision:
        item = self._resolve(incoming)
        status, reason, draft, gaps = _compose(incoming.text, item, self.catalog)
        note = _audit(reason, self.generator)
        if gaps:
            note = "待人工审阅。" + note + "缺口：" + "、".join(gaps) + "。"
        decision = Decision(
            case_id=incoming.case_id,
            status=status,
            reason=reason,
            matched_item_id=item.item_id if item else None,
            buyer_visible_draft=draft,
            audit_note=note,
            send_allowed=False,
            example=bool(item and item.example),
            generator=self.generator,
            model_invoked=False,
            mock_draft_rejected=self.generator == "mock",
        )
        problems = draft_safety_problems(draft, decision, self.catalog, incoming.text)
        if problems:
            decision = Decision(
                case_id=decision.case_id,
                status="handoff",
                reason="draft_rejected",
                matched_item_id=decision.matched_item_id,
                buyer_visible_draft="这句先不发，得再确认。",
                audit_note="待人工审阅。规则草稿未通过检查。未发送。",
                send_allowed=False,
                example=True,
                generator=self.generator,
                model_invoked=False,
                mock_draft_rejected=decision.mock_draft_rejected,
            )
        self.reviews.append(decision)
        return decision

    def deliver(self, decision: Decision, transport: Any = None) -> dict[str, Any]:
        """默认拒绝。transport 即使传入也不会被调用。"""
        del decision, transport
        self.send_attempts += 1
        return {"sent": False, "reason": "send_disabled"}

    def _resolve(self, incoming: Incoming) -> Optional[CatalogItem]:
        if incoming.trusted_item_id:
            item = self.catalog.by_id(incoming.trusted_item_id)
            if item is not None:
                self.bound[incoming.conversation_id] = item.item_id
            return item
        bound_id = self.bound.get(incoming.conversation_id)
        if bound_id:
            return self.catalog.by_id(bound_id)
        return None


def expectation_failures(decision: Decision, expect: dict, catalog: Catalog) -> list[str]:
    failures: list[str] = []
    for key in ("status", "reason", "matched_item_id", "send_allowed"):
        if key in expect and getattr(decision, key) != expect[key]:
            failures.append(f"{key}: 得到 {getattr(decision, key)!r}，期望 {expect[key]!r}")
    draft = decision.buyer_visible_draft
    for snippet in expect.get("must_contain", []):
        if snippet not in draft:
            failures.append(f"缺少 {snippet!r}: {draft}")
    for snippet in expect.get("must_not_contain", []):
        if snippet in draft:
            failures.append(f"不该出现 {snippet!r}: {draft}")
    if decision.send_allowed or decision.model_invoked:
        failures.append("发送或模型标记被打开")
    if "旧标价" in draft or incoming_echoes_note(draft):
        failures.append("草稿带出了内部说明")
    failures.extend(draft_safety_problems(draft, decision, catalog))
    return failures


def incoming_echoes_note(draft: str) -> bool:
    return "不能套到" in draft or "用户提到" in draft or "用户陈述" in draft


def run_replay(
    catalog: Catalog,
    cases: list[dict],
    generator: str = "rules",
) -> tuple[list[Decision], list[dict[str, Any]]]:
    engine = Engine(catalog, generator=generator)
    decisions: list[Decision] = []
    failures: list[dict[str, Any]] = []
    for case in cases:
        incoming = incoming_from_case(case)
        decision = engine.handle(incoming)
        decisions.append(decision)
        if generator == "mock":
            mock_problems = text_safety_problems(
                render_mock(incoming.text),
                allowed_price=None,
                allow_shipping=False,
            )
            if not mock_problems or not decision.mock_draft_rejected:
                failures.append({"id": case.get("id"), "failures": ["mock 没有被识别为违规或没有丢弃"]})
        case_failures = expectation_failures(decision, case.get("expect") or {}, catalog)
        if case_failures:
            failures.append({"id": case.get("id"), "failures": case_failures, "draft": decision.buyer_visible_draft})
    return decisions, failures
