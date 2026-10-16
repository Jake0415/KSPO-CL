"""Tests for agent.tools — Tool registry."""
from __future__ import annotations

import pytest

from kspo_ingest.agent.tools import ToolDef, ToolRegistry, _infer_parameters


class TestInferParameters:
    def test_simple_function(self):
        async def search(query: str, limit: int = 10) -> list:
            pass

        params = _infer_parameters(search)
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert params["properties"]["query"]["type"] == "string"
        assert params["properties"]["limit"]["type"] == "integer"
        assert "query" in params["required"]
        assert "limit" not in params["required"]

    def test_no_annotations(self):
        async def no_hints(x, y):
            pass

        params = _infer_parameters(no_hints)
        assert params["properties"]["x"]["type"] == "string"
        assert "x" in params["required"]

    def test_skips_self_and_ctx(self):
        async def method(self, ctx, query: str):
            pass

        params = _infer_parameters(method)
        assert "self" not in params["properties"]
        assert "ctx" not in params["properties"]
        assert "query" in params["properties"]


class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    def test_register_decorator(self, registry):
        @registry.register(description="Test tool")
        async def test_tool(query: str) -> str:
            return f"result: {query}"

        assert "test_tool" in registry
        assert len(registry) == 1

    def test_register_custom_name(self, registry):
        @registry.register(name="custom_name", description="Custom")
        async def some_function(x: int) -> int:
            return x * 2

        assert "custom_name" in registry
        assert "some_function" not in registry

    @pytest.mark.asyncio
    async def test_execute(self, registry):
        @registry.register(description="Add two numbers")
        async def add(a: int, b: int) -> int:
            return a + b

        result = await registry.execute("add", a=3, b=4)
        assert result == 7

    @pytest.mark.asyncio
    async def test_execute_missing_raises(self, registry):
        with pytest.raises(ValueError, match="Tool not found"):
            await registry.execute("nonexistent")

    def test_list_tools(self, registry):
        @registry.register(description="T1", category="search")
        async def s1():
            pass

        @registry.register(description="T2", category="browser")
        async def b1():
            pass

        all_tools = registry.list_tools()
        assert len(all_tools) == 2

        search_tools = registry.list_tools(category="search")
        assert len(search_tools) == 1
        assert search_tools[0].name == "s1"

    def test_to_openai_tools(self, registry):
        @registry.register(description="Search the web")
        async def web_search(query: str) -> str:
            return ""

        schemas = registry.to_openai_tools()
        assert len(schemas) == 1
        schema = schemas[0]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "web_search"
        assert "query" in schema["function"]["parameters"]["properties"]

    def test_add_direct(self, registry):
        async def my_fn(x: str) -> str:
            return x

        tool = ToolDef(name="direct", description="Directly added", fn=my_fn)
        registry.add(tool)
        assert "direct" in registry

    def test_tool_names(self, registry):
        @registry.register(description="A")
        async def alpha():
            pass

        @registry.register(description="B")
        async def beta():
            pass

        assert set(registry.tool_names) == {"alpha", "beta"}
