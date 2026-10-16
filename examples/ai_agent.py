"""AI Agent 예제 — 자연어로 브라우저 제어.

주의: LLM API 키 설정 필요 (OPENAI_API_KEY 또는 GEMINI_API_KEY).
"""
import asyncio

from kspo_ingest.agent.agent import Agent, AgentConfig


async def main():
    config = AgentConfig(
        max_steps=20,
        headless=True,  # True=headless, False=브라우저 표시
        stealth_profile="chrome_win",
    )

    # 자연어 작업 지시
    agent = Agent(
        task="KSPO 홈페이지(https://www.kspo.or.kr)에 접속해서 메인 페이지의 제목을 추출해줘",
        config=config,
    )

    result = await agent.run()

    print(f"Task: {result.task}")
    print(f"Success: {result.success}")
    print(f"Result: {result.result}")
    print(f"Steps: {result.steps_taken}")
    print(f"Elapsed: {result.elapsed_ms}ms")

    if result.extracted_data:
        print(f"Extracted: {result.extracted_data}")

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
