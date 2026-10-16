"""Tool registry — Agent가 사용할 수 있는 도구 등록/조회.

browser-use의 Tool 시스템을 참고하되, 데코레이터 기반 등록으로 개선.
Plugin에서도 도구를 등록할 수 있도록 열린 구조.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDef:
    """도구 정의."""

    name: str
    description: str
    fn: Callable[..., Coroutine[Any, Any, Any]]
    parameters: dict[str, Any] = field(default_factory=dict)
    category: str = "general"

    def to_openai_tool(self) -> dict[str, Any]:
        """OpenAI function calling 스키마로 변환."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


class ToolRegistry:
    """도구 레지스트리 — 등록 + 실행.

    사용법:
        registry = ToolRegistry()

        @registry.register(description="Search the web", category="search")
        async def web_search(query: str) -> str:
            ...

        result = await registry.execute("web_search", query="test")
        schemas = registry.to_openai_tools()
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        *,
        name: str | None = None,
        description: str = "",
        parameters: dict[str, Any] | None = None,
        category: str = "general",
    ) -> Callable:
        """데코레이터 — 함수를 도구로 등록."""

        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            tool_params = parameters
            if tool_params is None:
                tool_params = _infer_parameters(fn)

            tool = ToolDef(
                name=tool_name,
                description=description or fn.__doc__ or "",
                fn=fn,
                parameters=tool_params,
                category=category,
            )
            self._tools[tool_name] = tool
            return fn

        return decorator

    def add(self, tool: ToolDef) -> None:
        """직접 ToolDef 등록."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDef]:
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    async def execute(self, name: str, **kwargs: Any) -> Any:
        """도구 실행."""
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Tool not found: {name}")
        return await tool.fn(**kwargs)

    def to_openai_tools(self, category: str | None = None) -> list[dict[str, Any]]:
        """OpenAI function calling 스키마 목록."""
        return [t.to_openai_tool() for t in self.list_tools(category)]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def _infer_parameters(fn: Callable) -> dict[str, Any]:
    """함수 시그니처에서 JSON Schema 파라미터 추론."""
    import typing

    sig = inspect.signature(fn)
    # get_type_hints resolves stringified annotations from __future__
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    type_map: dict[type, str] = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "ctx"):
            continue

        annotation = hints.get(param_name, inspect.Parameter.empty)
        if annotation is inspect.Parameter.empty:
            json_type = "string"
        else:
            origin = getattr(annotation, "__origin__", None)
            if origin is not None:
                json_type = type_map.get(origin, "string")
            else:
                json_type = type_map.get(annotation, "string")

        properties[param_name] = {"type": json_type}

        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


# 글로벌 레지스트리 — 내장 도구 등록용
default_registry = ToolRegistry()
