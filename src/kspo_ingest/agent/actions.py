"""Browser actions — Agent가 실행할 수 있는 브라우저 액션 정의.

browser-use의 Action 시스템을 참고하되, Pydantic 모델 기반으로 재설계.
각 액션은 Tool calling의 function schema로도 사용 가능.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(StrEnum):
    GOTO = "goto"
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    SELECT = "select"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    EXTRACT_TEXT = "extract_text"
    EXTRACT_LINKS = "extract_links"
    EXECUTE_JS = "execute_js"
    GO_BACK = "go_back"
    DONE = "done"


class BrowserAction(BaseModel):
    """단일 브라우저 액션."""

    action: ActionType
    selector: str | None = None
    text: str | None = None
    url: str | None = None
    value: str | None = None
    direction: str | None = None
    amount: int | None = None
    js_code: str | None = None
    wait_ms: int | None = None
    reasoning: str = ""  # LLM이 왜 이 액션을 선택했는지

    def describe(self) -> str:
        """사람이 읽을 수 있는 액션 설명."""
        if self.action == ActionType.GOTO:
            return f"Navigate to {self.url}"
        if self.action == ActionType.CLICK:
            return f"Click on '{self.selector}'"
        if self.action == ActionType.TYPE:
            return f"Type '{self.text}' into '{self.selector}'"
        if self.action == ActionType.SCROLL:
            return f"Scroll {self.direction or 'down'} {self.amount or 300}px"
        if self.action == ActionType.SELECT:
            return f"Select '{self.value}' in '{self.selector}'"
        if self.action == ActionType.WAIT:
            return f"Wait {self.wait_ms or 1000}ms"
        if self.action == ActionType.EXTRACT_TEXT:
            return f"Extract text from '{self.selector or 'body'}'"
        if self.action == ActionType.EXTRACT_LINKS:
            return "Extract all links from page"
        if self.action == ActionType.SCREENSHOT:
            return "Take screenshot"
        if self.action == ActionType.EXECUTE_JS:
            return f"Execute JS: {(self.js_code or '')[:50]}"
        if self.action == ActionType.GO_BACK:
            return "Go back"
        if self.action == ActionType.DONE:
            return f"Task complete: {self.text or ''}"
        return f"Unknown action: {self.action}"


class ActionResult(BaseModel):
    """액션 실행 결과."""

    action: ActionType
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    elapsed_ms: int = 0


# Tool calling schema — LLM function calling에 사용
ACTION_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "browser_action",
        "description": "Execute a browser action on the current page",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [a.value for a in ActionType],
                    "description": "The action to perform",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the target element",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type or result message",
                },
                "url": {
                    "type": "string",
                    "description": "URL to navigate to",
                },
                "value": {
                    "type": "string",
                    "description": "Value to select in dropdown",
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "description": "Scroll direction",
                },
                "amount": {
                    "type": "integer",
                    "description": "Scroll amount in pixels",
                },
                "js_code": {
                    "type": "string",
                    "description": "JavaScript code to execute",
                },
                "wait_ms": {
                    "type": "integer",
                    "description": "Milliseconds to wait",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Why this action is needed",
                },
            },
            "required": ["action", "reasoning"],
        },
    },
}
