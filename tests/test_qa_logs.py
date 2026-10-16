from __future__ import annotations


def test_qa_log_model_exists():
    from kspo_ingest.db.models import QaLog
    log = QaLog(question="테스트 질문", answer="테스트 답변", is_answered=True)
    assert log.question == "테스트 질문"
    assert log.is_answered is True


def test_qa_log_unanswered():
    from kspo_ingest.db.models import QaLog
    log = QaLog(question="답변 못 받은 질문", is_answered=False, error_message="no_context")
    assert log.is_answered is False
    assert log.error_message == "no_context"


def test_qa_log_satisfaction():
    from kspo_ingest.db.models import QaLog
    log = QaLog(question="Q", answer="A", satisfaction=4)
    assert log.satisfaction == 4
