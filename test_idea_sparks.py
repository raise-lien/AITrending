"""Smoke tests for Idea Sparks normalization (no network)."""

from llm import _normalize_idea_sparks, extract_json


def test_normalize_idea_sparks():
    raw = {
        "idea_sparks": [
            {
                "name": "论文差分雷达",
                "one_liner": "把 ArXiv 新论文压成可做的 SaaS 切口",
                "signal": "多篇评估基准论文同日放出",
                "signal_urls": ["https://example.com/a", "https://example.com/b"],
                "opportunity": "我很难判断哪篇论文值得做成产品",
                "solution": "按能力缺口聚类并给出 MVP 草案",
                "perspective": "engineer",
                "why_now": "开源评测代码可复用",
                "mvp": "爬取 20 篇摘要，输出 3 个产品卡",
                "assumptions": ["开发者愿意为筛选付费", "摘要足以判断可产品化"],
                "scores": {"novelty": 4, "feasibility": 5, "impact": "3"},
            },
            {"name": "", "one_liner": "应被过滤"},
            {
                "name": "坏分",
                "one_liner": "测试非法分数",
                "perspective": "wizard",
                "scores": {"novelty": 9, "feasibility": "x"},
            },
        ],
        "idea_note": "今日偏工程可复用信号",
    }
    out = _normalize_idea_sparks(raw)
    assert len(out["idea_sparks"]) == 2
    first = out["idea_sparks"][0]
    assert first["perspective"] == "engineer"
    assert first["scores"]["impact"] == 3
    assert first["scores"]["novelty"] == 4
    second = out["idea_sparks"][1]
    assert second["perspective"] == "pm"  # invalid → default
    assert second["scores"]["novelty"] is None
    assert out["idea_note"].startswith("今日")


def test_extract_json_fence():
    text = '```json\n{"idea_note":"ok","idea_sparks":[]}\n```'
    data = extract_json(text)
    assert data["idea_note"] == "ok"


if __name__ == "__main__":
    test_normalize_idea_sparks()
    test_extract_json_fence()
    print("ok")
