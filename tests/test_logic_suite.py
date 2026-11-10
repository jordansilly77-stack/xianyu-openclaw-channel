"""云端用假模型跑多轮套件。不是用户 Mac 上的真实模型验收。"""

import json
from pathlib import Path

from kefu_offline.fixtures.sim_logic_suite import build_suite, suite_counts, write_catalog
from kefu_offline.suite_runner import EchoModel, evaluate_turn, run_suite


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
