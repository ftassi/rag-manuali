import httpx
from test_retrieval import settings_for

from manuali_rag.llm import LLMClient


def test_ollama_openai_compatible_request(tmp_path) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": " Risposta [S1]. "}}]})

    settings = settings_for(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    answer = LLMClient(settings, client=client).complete(user_text="Domanda", image_paths=[])

    assert answer == "Risposta [S1]."
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert captured["payload"]["model"] == "test"
    assert captured["payload"]["stream"] is False
