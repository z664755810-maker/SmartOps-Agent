import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Settings:
    def __init__(self) -> None:
        self.app_name = "SmartOps Agent"
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./data/agent.db")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_base_url = os.getenv(
            "LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        ).rstrip("/")
        self.llm_model = os.getenv("LLM_MODEL", "glm-4-flash")
        self.max_agent_steps = max(1, int(os.getenv("MAX_AGENT_STEPS", "5")))
        self.request_timeout_seconds = float(
            os.getenv("LLM_TIMEOUT_SECONDS", "45")
        )


settings = Settings()
