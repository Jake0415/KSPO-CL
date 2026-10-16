"""Task planner — 자연어 작업을 브라우저 액션 시퀀스로 분해.

browser-use의 Action Planner를 참고:
- 고수준 작업 → 단계별 계획 생성
- 실행 중 재계획 (에러 시 대안 탐색)
- LLM 기반 작업 분해
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from kspo_ingest.agent.actions import ActionType, BrowserAction
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.refine.provider import LlmProvider, get_provider

log = get_logger("agent", "planner")


@dataclass
class PlanStep:
    """계획의 단일 단계."""

    step: int
    description: str
    action: BrowserAction
    completed: bool = False
    retry_count: int = 0
    max_retries: int = 3


@dataclass
class TaskPlan:
    """작업 실행 계획."""

    task: str
    steps: list[PlanStep] = field(default_factory=list)
    current_step: int = 0
    is_complete: bool = False
    is_failed: bool = False
    error: str | None = None

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps if s.completed)
        return completed / len(self.steps)

    def next_step(self) -> PlanStep | None:
        for step in self.steps:
            if not step.completed:
                return step
        return None

    def mark_step_done(self, step_num: int) -> None:
        for step in self.steps:
            if step.step == step_num:
                step.completed = True
                self.current_step = step_num + 1
                break


class TaskPlanner:
    """LLM 기반 작업 플래너.

    사용법:
        planner = TaskPlanner()
        plan = await planner.create_plan("Search for Python tutorials on Google")
        # plan.steps → [PlanStep(...), ...]
    """

    def __init__(self, provider: LlmProvider | None = None) -> None:
        self._provider = provider

    def _get_provider(self) -> LlmProvider:
        return self._provider or get_provider()

    async def create_plan(self, task: str) -> TaskPlan:
        """자연어 작업에서 실행 계획 생성."""
        provider = self._get_provider()

        response = await provider.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a task planner. Break down web tasks into browser actions.\n"
                        "Respond with a JSON array of steps.\n"
                        "Each step: {\"step\": N, \"description\": \"...\", "
                        "\"action\": \"goto|click|type|scroll|extract_text|done\", "
                        "\"selector\": \"...\", \"url\": \"...\", \"text\": \"...\"}\n"
                        "Keep plans minimal and direct."
                    ),
                },
                {"role": "user", "content": f"Plan this task: {task}"},
            ],
            temperature=0.0,
        )

        raw = response.choices[0].message.content or "[]"
        return self._parse_plan(task, raw)

    def _parse_plan(self, task: str, raw_json: str) -> TaskPlan:
        """LLM 응답을 TaskPlan으로 파싱."""
        plan = TaskPlan(task=task)

        try:
            # JSON 블록 추출 (```json ... ``` 형태 대응)
            cleaned = raw_json.strip()
            if "```" in cleaned:
                start = cleaned.find("[")
                end = cleaned.rfind("]") + 1
                if start >= 0 and end > start:
                    cleaned = cleaned[start:end]

            steps_data = json.loads(cleaned)
            if not isinstance(steps_data, list):
                steps_data = [steps_data]

            for i, step_data in enumerate(steps_data):
                action_str = step_data.get("action", "done")
                try:
                    action_type = ActionType(action_str)
                except ValueError:
                    action_type = ActionType.DONE

                action = BrowserAction(
                    action=action_type,
                    selector=step_data.get("selector"),
                    text=step_data.get("text"),
                    url=step_data.get("url"),
                    value=step_data.get("value"),
                    reasoning=step_data.get("description", ""),
                )

                plan.steps.append(PlanStep(
                    step=i + 1,
                    description=step_data.get("description", ""),
                    action=action,
                ))

        except (json.JSONDecodeError, KeyError) as e:
            log.bind(event="plan_parse_error", error=str(e)).warning("plan parse failed")
            # 파싱 실패 시 단순 goto + done 계획
            plan.steps = [
                PlanStep(
                    step=1,
                    description=f"Execute task: {task}",
                    action=BrowserAction(
                        action=ActionType.DONE,
                        text=task,
                        reasoning="Direct execution",
                    ),
                ),
            ]

        return plan

    async def replan(
        self,
        original_plan: TaskPlan,
        error: str,
        current_state: str,
    ) -> TaskPlan:
        """에러 발생 시 대안 계획 생성."""
        provider = self._get_provider()

        response = await provider.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a task replanner. The original plan failed.\n"
                        "Create an alternative plan to complete the task.\n"
                        "Respond with a JSON array of steps."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original task: {original_plan.task}\n"
                        f"Error: {error}\n"
                        f"Current state: {current_state}\n"
                        f"Completed steps: {original_plan.current_step}\n"
                        "Create a new plan to complete the remaining work."
                    ),
                },
            ],
            temperature=0.1,
        )

        raw = response.choices[0].message.content or "[]"
        new_plan = self._parse_plan(original_plan.task, raw)
        log.bind(
            event="replanned",
            task=original_plan.task[:50],
            new_steps=len(new_plan.steps),
        ).info("replanned")
        return new_plan
