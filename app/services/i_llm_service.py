from abc import ABC, abstractmethod
from typing import AsyncIterator


class ILLMService(ABC):

    @abstractmethod
    async def generate(self, system_prompt: str, prompt: str) -> str:
        """Gọi LLM, trả về full response"""
        ...

    @abstractmethod
    async def stream(self, system_prompt: str, prompt: str) -> AsyncIterator[str]:
        """Gọi LLM, stream từng token"""
        ...