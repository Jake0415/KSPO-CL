// 콘솔 전역 공통 용어 설명 (InfoTip hover 툴팁용)

export const STATUS_MEANING: Record<string, string> = {
  INDEXED: '적재완료 — 챗봇이 실제로 사용하는 문서 (벡터DB 저장됨)',
  DROPPED: '제외 — 짧은 본문·오류·빈 페이지 등으로 학습 제외',
  DISCOVERED: '발견 — 링크는 찾았으나 아직 수집/처리 안 된 상태',
  FETCHED: '수집됨 — HTML을 받아온 직후 (정제 전)',
  CLEANED: '정제됨 — 본문 추출 완료 (임베딩 전)',
  REFINED: '정제완료 — LLM 정제까지 끝난 상태',
  ERROR: '오류 — 접속/추출 실패 (SSL·404·타임아웃 등)',
  REMOVED: '삭제 — 원본에서 사라져 지식DB에서 제거된 문서',
};

export const TERM = {
  docs: '문서 — 크롤로 수집한 개별 페이지(웹페이지 1개 = 문서 1개)',
  chunks: '청크 — 문서를 검색·임베딩 단위로 쪼갠 조각 (긴 문서는 여러 청크)',
  embeddings: '임베딩(벡터) — 청크를 숫자 벡터로 변환해 Qdrant에 저장한 것. 유사도 검색의 실제 대상',
  crawlHealth: '크롤 헬스 — 최근 20개 크롤 작업 중 성공 비율',
  coverage: '적재 커버리지 — 수집한 문서 중 실제 챗봇에 적재된 비율',
  freshness: '신선도 — 문서의 평균 최신성(게시일 기준 오래된 정도). 낮을수록 최신',
  jobSuccess: 'Job 성공률 — 최근 7일 크롤 작업의 성공 비율',
  cost: '월 LLM 비용 — 이번 달 누적 정제·임베딩 API 비용',
  newToday: '오늘 신규 — 오늘 처음 발견(discovered)된 문서 수',
  updatedToday: '오늘 갱신 — 오늘 재적재(indexed)된 문서 수',
  tokens: '토큰 수 — 청크의 길이(LLM 토큰 단위). 임베딩·비용 산정 기준',
  embed: '임베딩 상태 — 벡터 변환 성공/실패',
  kb: 'KB 상태 — 지식DB(Qdrant) 반영 성공/실패',
  extracted: '추출 본문 — 벡터DB에 실제 저장된 텍스트(제목·요약 헤더 + 본문). 챗봇이 이 텍스트로 검색·인용',
  depth: '탐색 깊이 — 시작 페이지에서 링크를 몇 번 따라간 페이지인지 (0 = 시작 페이지)',
};
