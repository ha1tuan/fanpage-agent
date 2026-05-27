from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.globals import set_llm_cache
from langchain_core.caches import InMemoryCache
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from functools import lru_cache
from typing import AsyncIterator
from app.core.settings import get_settings
from app.services.i_llm_service import ILLMService


# Bật cache trong RAM — cùng prompt không gọi lại LLM
set_llm_cache(InMemoryCache())


class GeminiLLMService(ILLMService):

    def __init__(self, temperature: float = 0.1):
        settings = get_settings()
        
        self._llm = ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=temperature,
            streaming=True,
            response_mime_type="application/json",
        )

    async def generate(self, system_prompt: str, prompt: str) -> str:
        """Gọi LLM, chờ full response rồi trả về"""
        response = await self._llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ])
        return response.content

    async def stream(self, system_prompt: str, prompt: str) -> AsyncIterator[str]:
        """Stream từng token về caller"""
        async for chunk in self._llm.astream(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        ):
            if chunk.content:
                yield chunk.content


class OllamaLLMService(ILLMService):

    def __init__(self, temperature: float = 0.1):
        settings = get_settings()
        self._llm = ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
            temperature=temperature,
        )

    async def generate(self, system_prompt: str, prompt: str) -> str:
        """Gọi Ollama, chờ full response rồi trả về"""
        response = await self._llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ])
        return response.content

    async def stream(self, system_prompt: str, prompt: str) -> AsyncIterator[str]:
        """Stream từng token từ Ollama"""
        async for chunk in self._llm.astream(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        ):
            if chunk.content:
                yield chunk.content


def get_chat_model(temperature: float = 0.1) -> BaseChatModel:
    """Trả về raw LangChain ChatModel (hỗ trợ bind_tools) cho create_react_agent."""
    settings = get_settings()
    if settings.LLM_PROVIDER == "ollama":
        return ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
            temperature=temperature,
        )
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=temperature,
    )


@lru_cache()
def get_llm_service(temperature: float = 0.1) -> ILLMService:
    """
    Singleton — tạo 1 lần duy nhất nhờ @lru_cache.
    Dùng cho FastAPI Depends().
    """
    settings = get_settings()
    if settings.LLM_PROVIDER == "ollama":
        print(f"🤖 Sử dụng local Ollama model: {settings.OLLAMA_MODEL}")
        return OllamaLLMService(temperature)
    
    print(f"🤖 Sử dụng Gemini model: {settings.GEMINI_MODEL}")
    return GeminiLLMService(temperature)