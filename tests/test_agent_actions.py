"""Tests for agent.actions — Browser action definitions."""
from __future__ import annotations

from kspo_ingest.agent.actions import (
    ACTION_TOOL_SCHEMA,
    ActionResult,
    ActionType,
    BrowserAction,
)


class TestActionType:
    def test_enum_values(self):
        assert ActionType.GOTO.value == "goto"
        assert ActionType.CLICK.value == "click"
        assert ActionType.DONE.value == "done"


class TestBrowserAction:
    def test_describe_goto(self):
        action = BrowserAction(action=ActionType.GOTO, url="https://example.com")
        assert "Navigate to https://example.com" == action.describe()

    def test_describe_click(self):
        action = BrowserAction(action=ActionType.CLICK, selector="#btn")
        assert "Click on '#btn'" == action.describe()

    def test_describe_type(self):
        action = BrowserAction(action=ActionType.TYPE, selector="#input", text="hello")
        assert "Type 'hello' into '#input'" == action.describe()

    def test_describe_done(self):
        action = BrowserAction(action=ActionType.DONE, text="Task complete")
        assert "Task complete: Task complete" == action.describe()


class TestActionResult:
    def test_success(self):
        result = ActionResult(action=ActionType.CLICK, success=True, elapsed_ms=50)
        assert result.success
        assert result.error is None

    def test_failure(self):
        result = ActionResult(
            action=ActionType.CLICK, success=False,
            error="Element not found", elapsed_ms=100,
        )
        assert not result.success
        assert result.error == "Element not found"


class TestToolSchema:
    def test_schema_structure(self):
        assert ACTION_TOOL_SCHEMA["type"] == "function"
        func = ACTION_TOOL_SCHEMA["function"]
        assert func["name"] == "browser_action"
        params = func["parameters"]
        assert "action" in params["properties"]
        assert "selector" in params["properties"]
        # enum 값 확인
        action_enum = params["properties"]["action"]["enum"]
        assert "goto" in action_enum
        assert "click" in action_enum
        assert "done" in action_enum
