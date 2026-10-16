"""Tests for agent.memory — Agent memory system."""
from __future__ import annotations

import pytest

from kspo_ingest.agent.memory import AgentMemory


class TestAgentMemory:
    def test_initial_state(self):
        mem = AgentMemory()
        assert mem.total_steps == 0
        assert mem.error_rate == 0.0

    def test_add_step(self):
        mem = AgentMemory()
        mem.add_step(step=1, action="click", result="ok", url="https://a.com")
        assert mem.total_steps == 1
        assert mem.error_rate == 0.0

    def test_error_tracking(self):
        mem = AgentMemory()
        mem.add_step(step=1, action="click", result="ok", success=True)
        mem.add_step(step=2, action="click", result="fail", success=False)
        assert mem.total_steps == 2
        assert mem.error_rate == 0.5

    def test_get_context(self):
        mem = AgentMemory()
        mem.set_task("Test task")
        mem.add_step(step=1, action="goto", result="loaded", url="https://example.com")
        ctx = mem.get_context()
        assert "Test task" in ctx
        assert "https://example.com" in ctx
        assert "goto" in ctx

    def test_compression(self):
        mem = AgentMemory(max_short_term=5)
        for i in range(10):
            mem.add_step(step=i, action=f"action_{i}", result="ok")
        # 최근 5개만 단기 기억에 유지
        assert len(mem._short_term) == 5
        # 장기 요약에 이전 항목 존재
        assert mem._long_term_summary != ""

    def test_get_recent_errors(self):
        mem = AgentMemory()
        mem.add_step(step=1, action="a", result="ok", success=True)
        mem.add_step(step=2, action="b", result="err1", success=False)
        mem.add_step(step=3, action="c", result="ok", success=True)
        mem.add_step(step=4, action="d", result="err2", success=False)
        errors = mem.get_recent_errors(2)
        assert len(errors) == 2
        assert errors[0].step == 2
        assert errors[1].step == 4

    def test_clear(self):
        mem = AgentMemory()
        mem.set_task("task")
        mem.add_step(step=1, action="a", result="ok")
        mem.clear()
        assert mem.total_steps == 0
        assert mem._short_term == []
        assert mem._long_term_summary == ""

    def test_long_term_truncation(self):
        mem = AgentMemory(max_short_term=2, max_long_term_chars=100)
        for i in range(50):
            mem.add_step(step=i, action=f"action_{i}", result="ok")
        assert len(mem._long_term_summary) <= 100
