"""Agent memory — 단기/장기 기억 관리.

browser-use의 Memory 개념을 개선:
- 단기 기억: 최근 N 스텝의 상태 + 결과
- 장기 기억: 요약 기반 압축 (토큰 절약)
- 작업 히스토리: 성공/실패 패턴 학습
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    """단일 기억 항목."""

    step: int
    action: str
    result: str
    url: str = ""
    success: bool = True
    timestamp: float = 0.0


@dataclass
class AgentMemory:
    """에이전트 메모리 — 컨텍스트 관리.

    사용법:
        memory = AgentMemory(max_short_term=20)
        memory.add_step(step=1, action="click", result="success", url="...")
        context = memory.get_context()  # LLM에 전달할 문자열
    """

    max_short_term: int = 20
    max_long_term_chars: int = 2000
    _short_term: list[MemoryEntry] = field(default_factory=list)
    _long_term_summary: str = ""
    _task_description: str = ""
    _current_url: str = ""
    _step_count: int = 0
    _error_count: int = 0

    def set_task(self, description: str) -> None:
        self._task_description = description

    def add_step(
        self,
        *,
        step: int,
        action: str,
        result: str,
        url: str = "",
        success: bool = True,
    ) -> None:
        entry = MemoryEntry(
            step=step, action=action, result=result,
            url=url, success=success,
        )
        self._short_term.append(entry)
        self._step_count += 1
        if not success:
            self._error_count += 1
        if url:
            self._current_url = url

        # 단기 기억 용량 초과 시 오래된 항목을 장기 요약으로 이동
        if len(self._short_term) > self.max_short_term:
            self._compress()

    def _compress(self) -> None:
        """오래된 단기 기억을 장기 요약으로 압축."""
        overflow = len(self._short_term) - self.max_short_term
        if overflow <= 0:
            return

        old_entries = self._short_term[:overflow]
        self._short_term = self._short_term[overflow:]

        # 간단한 요약 생성 (LLM 없이)
        summary_parts: list[str] = []
        for entry in old_entries:
            status = "OK" if entry.success else "FAIL"
            summary_parts.append(f"[{entry.step}] {entry.action} → {status}")

        new_summary = "; ".join(summary_parts)

        if self._long_term_summary:
            combined = f"{self._long_term_summary}\n{new_summary}"
            # 길이 제한
            if len(combined) > self.max_long_term_chars:
                combined = combined[-self.max_long_term_chars:]
            self._long_term_summary = combined
        else:
            self._long_term_summary = new_summary

    def get_context(self) -> str:
        """LLM에 전달할 메모리 컨텍스트 문자열."""
        parts: list[str] = []

        if self._task_description:
            parts.append(f"Task: {self._task_description}")

        if self._current_url:
            parts.append(f"Current URL: {self._current_url}")

        parts.append(f"Steps completed: {self._step_count}, Errors: {self._error_count}")

        if self._long_term_summary:
            parts.append(f"\nPrevious actions summary:\n{self._long_term_summary}")

        if self._short_term:
            parts.append("\nRecent actions:")
            for entry in self._short_term[-10:]:
                status = "OK" if entry.success else "FAIL"
                parts.append(f"  [{entry.step}] {entry.action} → {status}: {entry.result[:100]}")

        return "\n".join(parts)

    def get_recent_errors(self, n: int = 3) -> list[MemoryEntry]:
        """최근 N개 에러 항목."""
        errors = [e for e in self._short_term if not e.success]
        return errors[-n:]

    def clear(self) -> None:
        self._short_term.clear()
        self._long_term_summary = ""
        self._step_count = 0
        self._error_count = 0
        self._current_url = ""

    @property
    def total_steps(self) -> int:
        return self._step_count

    @property
    def error_rate(self) -> float:
        if self._step_count == 0:
            return 0.0
        return self._error_count / self._step_count
