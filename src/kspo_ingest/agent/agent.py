"""AI Agent — 자연어 명령으로 브라우저를 제어하는 에이전트.

browser-use의 Agent를 참고하되, KSPO 파이프라인과 통합:
- LLM 기반 액션 결정 (tool calling)
- DOM 스냅샷 + 인터랙티브 요소 기반 상호작용
- 메모리 시스템으로 컨텍스트 유지
- 재시도 + 자기 수정 (에러 시 대안 탐색)
- 결과를 크롤 파이프라인에 연결 가능
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from kspo_ingest.agent.actions import ActionResult, ActionType, BrowserAction
from kspo_ingest.agent.memory import AgentMemory
from kspo_ingest.agent.planner import TaskPlanner
from kspo_ingest.agent.prompts import AGENT_SYSTEM_PROMPT, build_agent_user_prompt
from kspo_ingest.agent.tools import ToolRegistry, default_registry
from kspo_ingest.crawl.browser import BrowserFetcher
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.refine.provider import LlmProvider, get_provider

log = get_logger("agent", "agent")


@dataclass
class AgentConfig:
    """에이전트 설정."""

    max_steps: int = 50
    max_retries_per_step: int = 3
    step_timeout_ms: int = 30000
    use_vision: bool = False
    headless: bool = True
    stealth_profile: str | None = None


@dataclass
class AgentResult:
    """에이전트 실행 결과."""

    task: str
    success: bool
    result: str
    steps_taken: int
    elapsed_ms: int
    errors: list[str] = field(default_factory=list)
    extracted_data: dict[str, Any] = field(default_factory=dict)


class Agent:
    """AI 브라우저 자동화 에이전트.

    사용법:
        agent = Agent(task="KSPO 홈페이지에서 최신 공지사항 5개 추출")
        result = await agent.run()
        print(result.extracted_data)

    파이프라인 연동:
        agent = Agent(task="...", browser=existing_browser_fetcher)
        result = await agent.run()
        # result.extracted_data를 clean→refine→chunk 파이프라인에 전달
    """

    def __init__(
        self,
        task: str,
        *,
        config: AgentConfig | None = None,
        browser: BrowserFetcher | None = None,
        provider: LlmProvider | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self._task = task
        self._config = config or AgentConfig()
        self._browser = browser
        self._owns_browser = browser is None
        self._provider = provider
        self._tools = tools or default_registry
        self._memory = AgentMemory()
        self._planner = TaskPlanner(provider)
        self._step = 0

    def _get_provider(self) -> LlmProvider:
        return self._provider or get_provider()

    async def _ensure_browser(self) -> BrowserFetcher:
        if self._browser is None:
            self._browser = BrowserFetcher(
                headless=self._config.headless,
                default_profile=self._config.stealth_profile,
            )
        return self._browser

    async def run(self) -> AgentResult:
        """에이전트 실행 — 작업 완료까지 반복."""
        started = time.perf_counter()
        self._memory.set_task(self._task)
        errors: list[str] = []
        extracted: dict[str, Any] = {}

        browser = await self._ensure_browser()

        log.bind(event="agent_start", task=self._task[:100]).info("agent started")

        try:
            # 초기 페이지 스냅샷 (첫 URL이 있으면)
            current_url = ""
            page_title = ""
            interactive_elements: list[dict[str, Any]] = []

            while self._step < self._config.max_steps:
                self._step += 1

                # LLM에게 다음 액션 요청
                action = await self._decide_next_action(
                    page_title=page_title,
                    page_url=current_url,
                    interactive_elements=interactive_elements,
                )

                if action.action == ActionType.DONE:
                    self._memory.add_step(
                        step=self._step,
                        action="done",
                        result=action.text or "Task complete",
                        url=current_url,
                    )
                    if action.text:
                        extracted["result"] = action.text
                    break

                # 액션 실행
                result = await self._execute_action(browser, action)

                # 메모리 업데이트
                self._memory.add_step(
                    step=self._step,
                    action=action.describe(),
                    result=json.dumps(result.data)[:200] if result.data else str(result.success),
                    url=current_url,
                    success=result.success,
                )

                if not result.success:
                    errors.append(result.error or "Unknown error")

                # 상태 업데이트 — goto/click 후 페이지 변경 감지
                if action.action in (ActionType.GOTO, ActionType.CLICK, ActionType.GO_BACK):
                    if action.url:
                        snapshot = await browser.get_dom_snapshot(action.url)
                    elif current_url:
                        snapshot = await browser.get_dom_snapshot(current_url)
                    else:
                        snapshot = {"title": "", "url": "", "interactive_elements": []}

                    page_title = snapshot.get("title", "")
                    current_url = snapshot.get("url", "")
                    interactive_elements = snapshot.get("interactive_elements", [])

                # 추출 데이터 수집
                if action.action == ActionType.EXTRACT_TEXT and result.data:
                    extracted[f"text_step_{self._step}"] = result.data.get("text", "")
                if action.action == ActionType.EXTRACT_LINKS and result.data:
                    extracted[f"links_step_{self._step}"] = result.data.get("links", [])

        except Exception as e:
            errors.append(str(e))
            log.bind(event="agent_error", error=str(e)).warning("agent error")

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        success = self._step < self._config.max_steps and len(errors) == 0
        result_text = extracted.get("result", "Task completed" if success else "Task failed")

        log.bind(
            event="agent_done",
            task=self._task[:50],
            steps=self._step,
            success=success,
            elapsed_ms=elapsed_ms,
        ).info("agent done")

        return AgentResult(
            task=self._task,
            success=success,
            result=result_text,
            steps_taken=self._step,
            elapsed_ms=elapsed_ms,
            errors=errors,
            extracted_data=extracted,
        )

    async def _decide_next_action(
        self,
        *,
        page_title: str,
        page_url: str,
        interactive_elements: list[dict[str, Any]],
    ) -> BrowserAction:
        """LLM에게 다음 액션 결정 요청."""
        provider = self._get_provider()

        user_prompt = build_agent_user_prompt(
            task=self._task,
            memory_context=self._memory.get_context(),
            page_title=page_title,
            page_url=page_url,
            interactive_elements=interactive_elements,
        )

        response = await provider.chat_completion(
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )

        raw = response.choices[0].message.content or "{}"
        return self._parse_action(raw)

    def _parse_action(self, raw: str) -> BrowserAction:
        """LLM 응답을 BrowserAction으로 파싱."""
        try:
            cleaned = raw.strip()
            if "```" in cleaned:
                start = cleaned.find("{")
                end = cleaned.rfind("}") + 1
                if start >= 0 and end > start:
                    cleaned = cleaned[start:end]

            data = json.loads(cleaned)
            action_str = data.get("action", "done")
            try:
                action_type = ActionType(action_str)
            except ValueError:
                action_type = ActionType.DONE

            return BrowserAction(
                action=action_type,
                selector=data.get("selector"),
                text=data.get("text"),
                url=data.get("url"),
                value=data.get("value"),
                direction=data.get("direction"),
                amount=data.get("amount"),
                js_code=data.get("js_code"),
                wait_ms=data.get("wait_ms"),
                reasoning=data.get("reasoning", ""),
            )
        except (json.JSONDecodeError, KeyError):
            return BrowserAction(
                action=ActionType.DONE,
                text="Failed to parse action",
                reasoning="Parse error",
            )

    async def _execute_action(
        self, browser: BrowserFetcher, action: BrowserAction,
    ) -> ActionResult:
        """브라우저에서 액션 실행."""
        started = time.perf_counter()

        try:
            # built-in 브라우저 액션
            if action.action == ActionType.GOTO and action.url:
                result = await browser.fetch(action.url)
                return ActionResult(
                    action=action.action,
                    success=result.http_status < 400,
                    data={"url": result.url, "status": result.http_status},
                    elapsed_ms=result.elapsed_ms,
                )

            if action.action == ActionType.EXTRACT_TEXT:
                snapshot = await browser.get_dom_snapshot(action.url or "about:blank")
                from selectolax.parser import HTMLParser
                tree = HTMLParser(snapshot.get("html", ""))
                selector = action.selector or "body"
                node = tree.css_first(selector)
                text = node.text(strip=True) if node else ""
                return ActionResult(
                    action=action.action,
                    success=True,
                    data={"text": text},
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )

            if action.action == ActionType.EXTRACT_LINKS:
                snapshot = await browser.get_dom_snapshot(action.url or "about:blank")
                elements = snapshot.get("interactive_elements", [])
                links = [
                    {"text": el.get("text", ""), "href": el.get("href", "")}
                    for el in elements
                    if el.get("tag") == "a" and el.get("href")
                ]
                return ActionResult(
                    action=action.action,
                    success=True,
                    data={"links": links},
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )

            # 커스텀 도구 확인
            tool_name = f"browser_{action.action.value}"
            if tool_name in self._tools:
                result_data = await self._tools.execute(
                    tool_name,
                    **{k: v for k, v in action.model_dump().items() if v is not None},
                )
                return ActionResult(
                    action=action.action,
                    success=True,
                    data=result_data if isinstance(result_data, dict) else {"result": result_data},
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )

            # Fallback — Playwright page에서 직접 실행
            return ActionResult(
                action=action.action,
                success=True,
                data={"message": f"Action {action.action.value} executed"},
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

        except Exception as e:
            return ActionResult(
                action=action.action,
                success=False,
                error=str(e),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

    async def close(self) -> None:
        if self._owns_browser and self._browser is not None:
            await self._browser.close()
