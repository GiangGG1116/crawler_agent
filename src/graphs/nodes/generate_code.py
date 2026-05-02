"""Node: generate_crawler_code — Generate custom crawler from analysis report.

Uses LLM to generate a Python crawler script tailored to the analyzed website.
Follows code generation rules R1-R6 from the implementation plan.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from src.graphs.state import AgentGraphState
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

CODEGEN_PROMPT = """You are a Python web scraping expert. Generate a production-quality crawler script based on this analysis.

## Analysis
URL: {url}
DOM Structure: {dom_structure}
Pagination: {pagination}
Challenges: {challenges}
Recommended Tool: {tool}
Required Fields: {required_fields}
Rate Limit: {rate_limit} requests/second

## Code Requirements (MUST follow all):
R1: Error handling for every HTTP request (try/except with logging)
R2: Retry logic with exponential backoff (3 retries max)
R3: Respect rate_limit from analysis
R4: Handle missing fields gracefully (return None, never crash)
R5: Logging for each page crawled
R6: Output must conform to required_fields: {required_fields}

## Output Format
Generate a single Python file with:
- An async `crawl(url, max_pages, max_records)` function that returns List[dict]
- Proper imports
- Error handling
- Rate limiting

Output ONLY the Python code, no markdown wrapping.
"""


def _get_llm():
    settings = get_settings()
    if settings.default_llm_provider.value == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", api_key=settings.openai_api_key, temperature=0)
    else:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-sonnet-4-20250514", api_key=settings.anthropic_api_key, temperature=0)


async def generate_crawler_code(state: AgentGraphState) -> dict[str, Any]:
    """Generate custom crawler code from analysis."""
    analysis = state.get("analysis", {})
    request_id = state.get("request_id", "unknown")
    attempt = state.get("attempt", 1)

    logger.info(f"[Attempt {attempt}] Generating crawler code", extra={"request_id": request_id, "phase": "phase2"})

    llm = _get_llm()
    prompt = CODEGEN_PROMPT.format(
        url=state["target_url"],
        dom_structure=json.dumps(analysis.get("dom_structure", {}), indent=2),
        pagination=json.dumps(analysis.get("pagination", {}), indent=2),
        challenges=json.dumps(analysis.get("challenges", []), indent=2),
        tool=analysis.get("recommendation", {}).get("tool", "playwright"),
        required_fields=", ".join(state.get("required_fields", [])),
        rate_limit=state.get("rate_limit_rps", 2),
    )

    response = await llm.ainvoke(prompt)
    code_content = response.content if isinstance(response.content, str) else ""

    # Clean markdown if present
    if code_content.startswith("```"):
        code_content = code_content.split("\n", 1)[1]
        code_content = code_content.rsplit("```", 1)[0]

    # Save generated files
    settings = get_settings()
    output_dir = settings.generated_crawlers_dir
    crawler_id = request_id[:8]

    crawler_file = output_dir / f"crawler_{crawler_id}.py"
    config_file = output_dir / f"config_{crawler_id}.json"

    crawler_file.write_text(code_content, encoding="utf-8")
    config_data = {
        "request_id": request_id,
        "url": state["target_url"],
        "analysis": analysis,
        "attempt": attempt,
    }
    config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    logger.info(f"Generated crawler: {crawler_file.name}", extra={"request_id": request_id})

    return {
        "generated": {
            "files": [
                {"filename": crawler_file.name, "content": code_content},
                {"filename": config_file.name, "content": json.dumps(config_data)},
            ],
            "entrypoint": str(crawler_file),
        }
    }
