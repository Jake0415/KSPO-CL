import unittest

from kspo_ingest.clean.rag import document_content, normalize_text, preserve_references


class RagPreparationTest(unittest.TestCase):
    def test_normalization_preserves_facts_and_table_rows(self):
        text = (
            "\ufeff작품명\r\n작품명\r조회수: 1,234\n닫기\n"
            "재료 | 철근 콘크리트\n"
            "크기 1009X5.0X7.0 (m)\n작가\n작품명"
        )
        result = normalize_text(text)
        self.assertEqual(
            result, "작품명\n재료 | 철근 콘크리트\n크기 1009X5.0X7.0 (m)\n작가\n작품명"
        )
        self.assertEqual(normalize_text(" a\t b\u00a0c\u200b "), "a b c")
        self.assertEqual(normalize_text(result), result)
        self.assertEqual(normalize_text(" \n "), "")

    def test_references_restore_without_duplicates(self):
        original = "작품 설명\n이미지: https://soma.kspo.or.kr/a.jpg\n첨부파일\na.pdf\nhttps://soma.kspo.or.kr/file/a\nhttps://soma.kspo.or.kr/file/b"
        result = preserve_references("작품 설명", original)
        self.assertIn("a.pdf\nhttps://soma.kspo.or.kr/file/a", result)
        self.assertIn("이미지: https://soma.kspo.or.kr/a.jpg", result)
        self.assertIn("https://soma.kspo.or.kr/file/b", result)
        self.assertEqual(preserve_references(result, original), result)
        self.assertEqual(preserve_references("본문", "본문"), "본문")

    def test_document_source_and_summary(self):
        args = {
            "title": "작품",
            "source_url": "https://soma.kspo.or.kr/piece/1",
            "body": "재료 | 철근 콘크리트",
        }
        result = document_content(**args, summary="작품")
        self.assertIn("출처: https://soma.kspo.or.kr/piece/1", result)
        self.assertNotIn("요약:", result)
        self.assertIn("재료 | 철근 콘크리트", result)
        self.assertIn("요약: 조각 정보", document_content(**args, summary="조각 정보"))
        self.assertNotIn("요약:", document_content(**args, summary=None))
        self.assertNotIn("요약:", document_content(**args, summary=args["body"]))


class RagEnrichmentTest(unittest.TestCase):
    def test_preserves_original_facts(self):
        from kspo_ingest.clean.rag import enriched_content

        original = "작품명 열림\n제작연도 1988년\n재료 철근 콘크리트"
        result = enriched_content(original, "[검색 보강]\n이 작품의 제작연도는 1988년입니다.")
        self.assertIn(original, result)
        self.assertIn("[원문 정보]", result)
        self.assertIn("[LLM 정제·검색 보강]", result)
        self.assertEqual(enriched_content(original, original), original)
        self.assertEqual(enriched_content(original, ""), original)


class RefinePolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_false_meaningful_is_not_dropped(self):
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from kspo_ingest.clean.rag import enriched_content, normalize_text

        path = Path(__file__).parents[1] / "src/kspo_ingest/tasks/pipeline/refine_page.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(
            n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "refine_page"
        )
        module = ast.Module(body=[function], type_ignores=[])
        refined = SimpleNamespace(is_meaningful=False, refined_text="검색 보강 문장")
        refined.model_dump = lambda: {
            "is_meaningful": refined.is_meaningful,
            "refined_text": refined.refined_text,
        }
        session = MagicMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=False)
        drop = AsyncMock()
        mark = AsyncMock()
        namespace = {
            "normalize_text": normalize_text,
            "enriched_content": enriched_content,
            "is_cancelled": AsyncMock(return_value=False),
            "do_refine": AsyncMock(
                return_value=SimpleNamespace(usage=None, drop=False, refined=refined)
            ),
            "mark_refined": mark,
            "bump_stats": AsyncMock(),
            "mark_dropped": drop,
            "_purge_existing_chunks": AsyncMock(),
        }
        exec(compile(module, str(path), "exec"), namespace)
        result = await namespace["refine_page"](
            {"session_factory": lambda: context},
            job_id=1,
            page_id=2,
            title="작품",
            body_text="제작연도 1988년 원문 정보",
            content_hash="hash",
        )
        self.assertTrue(result["refined"]["is_meaningful"])
        self.assertIn("제작연도 1988년", result["refined"]["refined_text"])
        drop.assert_not_awaited()
        mark.assert_awaited_once()
