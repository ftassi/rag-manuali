import httpx

from manuali_rag.embeddings import OpenAIEmbedder


def test_ollama_openai_compatible_embeddings_request() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 2.0]},
                    {"index": 0, "embedding": [3.0, 0.0]},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    embedder = OpenAIEmbedder("http://127.0.0.1:11434/v1", "nomic-embed-text", 1, client=client)

    vectors = embedder.embed(["primo", "secondo"])

    assert captured["url"] == "http://127.0.0.1:11434/v1/embeddings"
    assert captured["payload"] == {
        "model": "nomic-embed-text",
        "input": ["primo", "secondo"],
    }
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
