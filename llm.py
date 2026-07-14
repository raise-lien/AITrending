"""
DeepSeek (OpenAI-compatible) LLM client for Chinese summarization & daily digest.
Credentials loaded from .env / environment — never hardcode keys.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

# Load .env if present (python-dotenv optional; fallback to manual parse)
def _load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        return
    except ImportError:
        pass
    # Minimal fallback parser
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


_load_dotenv()


def get_api_key() -> str | None:
    return (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or None
    )


def get_base_url() -> str:
    return (
        os.environ.get("LLM_BASE_URL")
        or os.environ.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com/v1"
    ).rstrip("/")


def get_model() -> str:
    return os.environ.get("LLM_MODEL") or "deepseek-chat"


def is_configured() -> bool:
    return bool(get_api_key())


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> str:
    """Call DeepSeek chat completions. Returns assistant text content."""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not set. Copy .env.example to .env and fill in your key."
        )

    url = f"{get_base_url()}/chat/completions"
    payload = {
        "model": get_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected LLM response: {data!r}") from e


def extract_json(text: str) -> Any:
    """Extract JSON object/array from model output (handles markdown fences)."""
    text = text.strip()
    # Strip ```json ... ``` fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find outermost { ... } or [ ... ]
        for open_c, close_c in (("{", "}"), ("[", "]")):
            start = text.find(open_c)
            end = text.rfind(close_c)
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
        raise


DIGEST_SYSTEM = """你是一位资深 AI 行业编辑。根据候选新闻生成「今日 AI 简报」。
要求：
1. 全部使用简体中文
2. 只输出一个合法 JSON 对象，不要 markdown，不要解释
3. 字段：
{
  "hero_headline": "一句话今日头条（≤40字）",
  "daily_overview": "2-4 句今日综述",
  "briefs": [
    {
      "title": "中文标题（可意译）",
      "url": "原文链接（必须来自候选）",
      "source": "来源名",
      "summary": "2-3 句中文摘要，说清楚发生了什么、为何重要",
      "importance": 1到5的整数
    }
  ],
  "editor_note": "一句编辑点评",
  "keywords": ["关键词1", "关键词2", "..."]
}
4. briefs 选 8-15 条最重要的，按 importance 降序
5. 不要编造候选列表里没有的链接
6. 忽略明显广告/无关内容
"""


def generate_digest_from_candidates(candidates: list[dict]) -> dict:
    """
    candidates: [{title, url, source, excerpt, published?}, ...]
    Returns parsed digest dict.
    """
    # Keep payload compact
    slim = []
    for c in candidates:
        slim.append({
            "title": (c.get("title") or "")[:200],
            "url": c.get("url") or c.get("link") or "",
            "source": c.get("source") or c.get("feed_name") or "",
            "excerpt": (c.get("excerpt") or c.get("summary") or "")[:400],
            "published": c.get("published_ts") or c.get("published") or "",
        })

    user = (
        "以下是今日候选 AI 资讯（JSON）。请生成今日简报：\n"
        + json.dumps(slim, ensure_ascii=False)
    )
    raw = chat(
        [
            {"role": "system", "content": DIGEST_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.35,
        max_tokens=5000,
    )
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Digest response is not a JSON object")
    # Normalize
    data.setdefault("hero_headline", "")
    data.setdefault("daily_overview", "")
    data.setdefault("briefs", [])
    data.setdefault("editor_note", "")
    data.setdefault("keywords", [])
    data["_model"] = get_model()
    return data


ENRICH_SYSTEM = """你是翻译兼摘要助手。对每条英文 AI 资讯给出简洁中文摘要。
只输出 JSON 数组：[{"url":"...","zh_summary":"1-2句中文"}, ...]
不要编造 url，必须与输入一致。不要 markdown。"""


def enrich_zh_summaries(items: list[dict], batch_size: int = 12) -> dict[str, str]:
    """
    items: [{url/link, title, summary/excerpt}, ...]
    Returns {url: zh_summary}.
    """
    result: dict[str, str] = {}
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        slim = []
        for it in batch:
            url = it.get("url") or it.get("link") or ""
            slim.append({
                "url": url,
                "title": (it.get("title") or "")[:180],
                "excerpt": (it.get("excerpt") or it.get("summary") or "")[:350],
            })
        raw = chat(
            [
                {"role": "system", "content": ENRICH_SYSTEM},
                {"role": "user", "content": json.dumps(slim, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        parsed = extract_json(raw)
        if isinstance(parsed, list):
            for row in parsed:
                if isinstance(row, dict) and row.get("url") and row.get("zh_summary"):
                    result[row["url"]] = str(row["zh_summary"]).strip()
    return result
