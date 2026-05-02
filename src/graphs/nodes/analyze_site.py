"""Node: analyze_site — Inspect website structure for custom crawler generation.

Uses headless browser to render the page, detect selectors, pagination,
anti-bot measures, and generate an analysis report.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.graphs.state import AgentGraphState
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _get_llm():
    """Get configured LLM for analysis."""
    from src.utils.config import get_settings
    settings = get_settings()

    if settings.default_llm_provider.value == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0)
    else:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-sonnet-4-20250514", api_key=settings.anthropic_api_key, temperature=0)


ANALYZE_PROMPT = """You are a web scraping expert. Analyze the following website HTML and provide a structured analysis for building a custom crawler.

URL: {url}
Web Type: {web_type}
Required Fields: {required_fields}
Template Failure Reason: {failure_reason}

HTML Content (first 10000 chars):
```html
{html_content}
```

Respond with a JSON object containing:
{{
  "dom_structure": {{
    "content_container": "CSS selector for the main content area",
    "item_selector": "CSS selector for individual items",
    "field_map": {{
      "field_name": {{"selector": "CSS selector", "method": "text|attribute", "attr": "optional attribute name"}}
    }}
  }},
  "pagination": {{
    "type": "page_number|next_button|infinite_scroll|load_more|none",
    "pattern": "URL pattern if applicable",
    "selector": "CSS selector if applicable"
  }},
  "challenges": [
    {{"type": "challenge_type", "detail": "description"}}
  ],
  "recommendation": {{
    "tool": "playwright|requests|scrapy",
    "strategy": "render_then_parse|direct_fetch|api_intercept"
  }}
}}

Only output valid JSON, no markdown.
"""
    

async def analyze_site(state: AgentGraphState) -> dict[str, Any]:
    """
    Node: Analyze the target website structure.

    Uses a headless browser to render the page, then sends the HTML
    to an LLM for structured analysis.
    """
    url = state["target_url"]
    attempt = state.get("attempt", 1)
    request_id = state.get("request_id", "unknown")

    logger.info(
        f"[Attempt {attempt}] Analyzing site: {url}",
        extra={"request_id": request_id, "phase": "phase2"},
    )

    # Fetch rendered HTML
    html_content = await _fetch_rendered_html(url)

    # Get failure context
    template_failure = state.get("template_failure", {})
    failure_reason = template_failure.get("reason", "Unknown")

    # Call LLM for analysis
    llm = _get_llm()
    prompt = ANALYZE_PROMPT.format(
        url=url,
        web_type=state.get("web_type", "UNKNOWN"),
        required_fields=", ".join(state.get("required_fields", [])),
        failure_reason=failure_reason,
        html_content=html_content[:10000],
    )

    response = await llm.ainvoke(prompt)

    # Parse LLM response
    import json
    try:
        content = response.content
        if isinstance(content, str):
            # Clean potential markdown wrapping
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            analysis_data = json.loads(content)
        else:
            analysis_data = {}
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM analysis response")
        analysis_data = {"dom_structure": {}, "pagination": {}, "challenges": [], "recommendation": {}}

    analysis = {
        "analysis_id": str(uuid.uuid4()),
        "url": url,
        **analysis_data,
    }

    logger.info(f"Analysis complete: {analysis.get('recommendation', {})}", extra={"request_id": request_id})

    return {"analysis": analysis}


async def _fetch_rendered_html(url: str) -> str:
    """Fetch and render page HTML using Playwright."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        logger.warning(f"Playwright render failed, falling back to HTTP: {e}")
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            return resp.text
