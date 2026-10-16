"""Agent prompts — LLM에 전달하는 시스템/유저 프롬프트 템플릿."""
from __future__ import annotations

from typing import Any

AGENT_SYSTEM_PROMPT = """You are a web automation agent. You control a browser to complete tasks.

## Capabilities
You can perform these browser actions:
- goto: Navigate to a URL
- click: Click on an element (by CSS selector)
- type: Type text into an input field
- scroll: Scroll the page up or down
- select: Select an option in a dropdown
- wait: Wait for a specified time
- extract_text: Extract text from an element
- extract_links: Extract all links from the page
- execute_js: Execute JavaScript code
- go_back: Go back to the previous page
- done: Indicate the task is complete

## Rules
1. Always provide a CSS selector when clicking or typing
2. Use the interactive elements list to find valid selectors
3. If an action fails, try an alternative approach
4. When the task is complete, use the 'done' action with the result
5. Be efficient - minimize unnecessary actions
6. If stuck after 3 failed attempts on the same element, try a different strategy

## Response Format
Respond with a JSON object containing your next action:
{
    "action": "click",
    "selector": "#submit-btn",
    "reasoning": "Clicking the submit button to complete the form"
}
"""


def build_agent_user_prompt(
    *,
    task: str,
    memory_context: str,
    page_title: str,
    page_url: str,
    interactive_elements: list[dict[str, Any]],
) -> str:
    """Agent에게 전달할 유저 프롬프트 생성."""
    elements_text = _format_elements(interactive_elements)

    return f"""## Current Task
{task}

## Memory
{memory_context}

## Current Page
Title: {page_title}
URL: {page_url}

## Interactive Elements on Page
{elements_text}

## Your Next Action
Analyze the current state and decide the next action to complete the task.
Respond with a single JSON action object.
"""


def _format_elements(elements: list[dict[str, Any]], max_items: int = 50) -> str:
    """인터랙티브 요소 목록을 텍스트로 포맷."""
    if not elements:
        return "(No interactive elements found)"

    lines: list[str] = []
    for el in elements[:max_items]:
        tag = el.get("tag", "?")
        text = el.get("text", "")[:60]
        href = el.get("href", "")
        el_id = el.get("id", "")
        el_class = el.get("class", "")
        el_type = el.get("type", "")

        # 가장 구체적인 셀렉터 생성
        selector_parts: list[str] = [tag]
        if el_id:
            selector_parts = [f"#{el_id}"]
        elif el_class:
            first_class = el_class.split()[0]
            selector_parts = [f"{tag}.{first_class}"]

        selector = "".join(selector_parts)

        desc_parts: list[str] = [f"[{selector}]"]
        if text:
            desc_parts.append(f'"{text}"')
        if href:
            desc_parts.append(f"→ {href[:80]}")
        if el_type:
            desc_parts.append(f"(type={el_type})")

        lines.append(" ".join(desc_parts))

    result = "\n".join(lines)
    if len(elements) > max_items:
        result += f"\n... and {len(elements) - max_items} more elements"
    return result


PLANNER_SYSTEM_PROMPT = """You are a task planning agent. Given a high-level task description,
break it down into concrete browser actions.

Respond with a JSON array of steps:
[
    {"step": 1, "description": "Navigate to the target website", "action": "goto", "url": "..."},
    {"step": 2, "description": "Find the search box", "action": "click", "selector": "..."},
    ...
]

Keep plans simple and direct. Prefer fewer steps over many small steps.
"""
