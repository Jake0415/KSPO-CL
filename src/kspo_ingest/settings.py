from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    app_env: str = "development"
    app_port: int = 8080
    timezone: str = "Asia/Seoul"

    # Auth
    admin_username: str = "admin"
    admin_password_bcrypt: str
    session_secret: str
    session_max_age_seconds: int = 28_800  # 8h, 일과 기준
    login_max_attempts: int = 5
    login_lockout_seconds: int = 300  # 5 minutes

    # Database
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "kspo_ingest"
    postgres_user: str
    postgres_password: str

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # OpenAI
    openai_api_key: str = ""
    openai_refine_model: str = "gpt-5.4-mini"
    openai_embed_model: str = "text-embedding-3-large"
    openai_monthly_budget_krw: int = 150_000

    # LLM Provider (openai | gemini)
    llm_provider: str = "openai"

    # Gemini (OpenAI-compatible endpoint)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Qdrant — dual mode (dev/pilot: container, prod: Tiledesk external)
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_index_name: str = "tilellm"
    # 검색 대상 named vector 이름. 빈값이면 unnamed(default) 벡터로 조회한다.
    # 자체 컨테이너 모드(리포 bootstrap)는 unnamed → "", Tiledesk 외부 인스턴스는
    # named vector("text-dense")를 쓰므로 QDRANT_VECTOR_NAME=text-dense로 지정.
    qdrant_vector_name: str = ""
    kb_namespace: str = "kspo"
    embedding_version: int = 1
    qdrant_knowledge_collection: str = "kspo_knowledge"
    qdrant_archive_collection: str = "kspo_archive"
    # `managed`: API startup에서 ensure_collection() 호출 (자체 컨테이너 모드 권장)
    # `external`: bootstrap 생략 (Tiledesk 측이 컬렉션 관리)
    kb_bootstrap: str = "managed"

    # Internal proxy (api/worker only — injected via compose env)
    https_proxy: str = ""
    http_proxy: str = ""
    no_proxy: str = "localhost,127.0.0.1,postgres,redis,qdrant,host.docker.internal"

    # Crawl
    crawl_user_agent_default: str = "kspo-ingest/0.2 (+admin@example.com)"
    storage_root: str = "/data"
    crawl_render_all_html: bool = True
    crawl_dynamic_max_actions: int = 100
    crawl_initial_ready_timeout_ms: int = 15000
    crawl_action_ready_timeout_ms: int = 5000
    crawl_content_stable_ms: int = 800

    # Refine
    ko_ratio_threshold: float = 0.30
    usd_to_krw_rate: float = 1370.0

    # Chunking (M3.T3.1에서 사용)
    chunk_long_threshold_tokens: int = 800
    chunk_target_tokens: int = 600
    chunk_overlap_tokens: int = 80

    # Board crawling
    board_freshness_days: int = 90  # 3-month window

    # Stealth / Proxy
    stealth_profile: str = ""  # chrome_win, chrome_mac, edge_win, firefox_win
    proxy_urls: str = ""  # 콤마 구분 프록시 URL 목록

    # Spider
    spider_concurrency: int = 8
    spider_max_depth: int = 10
    spider_max_pages: int = 20000

    # Agent
    agent_max_steps: int = 50
    agent_headless: bool = True

    # Metrics
    metrics_enabled: bool = False

    # Plugins (콤마 구분 모듈 경로)
    plugin_modules: str = ""

    # Logging / migrations
    log_level: str = "INFO"
    log_format: str = "json"
    log_max_field_len: int = 8000
    alembic_auto: bool = False

    # SONAR (tiledesk-llm) integration — 파이프라인 인덱싱 대상.
    # `""`일 때 push_to_sonar 스텝은 즉시 no-op (개발/PoC에서 로컬 실행 시 안전).
    sonar_base_url: str = ""
    sonar_project_id: str = ""
    sonar_namespace: str = ""
    sonar_email: str = ""
    sonar_password: str = ""
    sonar_timeout_seconds: float = 60.0
    sonar_retry_max: int = 3
    sonar_retry_backoff_seconds: float = 1.0

    # Alerts (SMTP) — KSPO 사내 SMTP 가정
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    # 콤마 구분 다중 수신자
    smtp_to_recipients: str = ""


settings = Settings()
