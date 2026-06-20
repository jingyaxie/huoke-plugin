from openai import AsyncOpenAI

from app.core.config import Settings


class AIClientFactory:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def deepseek(self) -> AsyncOpenAI | None:
        if not self.settings.deepseek_api_key:
            return None
        return AsyncOpenAI(api_key=self.settings.deepseek_api_key, base_url=self.settings.deepseek_base_url)

    def llm_client(self) -> AsyncOpenAI | None:
        return self.deepseek()

    def llm_configured(self) -> bool:
        return self.deepseek() is not None

    def llm_model(self) -> str:
        return self.settings.deepseek_model

