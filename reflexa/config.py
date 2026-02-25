from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///reflexa.db"

    # LLM
    openai_api_key: str = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_timeout: int = 30

    # Logging
    log_level: str = "INFO"

    # Pipeline behaviour
    memory_turns: int = 10
    max_message_length: int = 2000
    display_condition: Literal["baseline", "corrected"] = "baseline"

    # Prompt version overrides (empty string → use latest)
    baseline_prompt_version: str = ""
    pipeline_draft_prompt_version: str = ""
    pipeline_verifier_prompt_version: str = ""
    pipeline_critic_prompt_version: str = ""
    pipeline_reviser_prompt_version: str = ""
    eval_judge_prompt_version: str = ""
    session_opener_prompt_version: str = ""

    # Evaluation
    eval_judge_model: str = "gpt-4o-mini"

    # API server
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Streamlit
    backend_url: str = "http://localhost:8000"

    @property
    def is_mock(self) -> bool:
        return self.openai_api_key.lower() == "mock"


settings = Settings()
