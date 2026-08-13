from fastapi.testclient import TestClient
from test_retrieval import settings_for

from manuali_rag.api import create_app


def test_api_starts_and_answers_empty_index(tmp_path) -> None:
    app = create_app(settings_for(tmp_path))
    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["index"] == {"documents": 0, "chunks": 0}

    response = client.post(
        "/api/questions",
        json={"question": "Come si pulisce il filtro?", "include_images": True},
    )
    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert "Non ho trovato" in response.json()["answer"]
