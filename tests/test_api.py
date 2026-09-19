from test_retrieval import settings_for

from manuali_rag.api import QuestionRequest, create_app


def test_api_starts_and_answers_empty_index(tmp_path) -> None:
    app = create_app(settings_for(tmp_path))
    endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, "path")}

    health = endpoints["/api/health"]()
    assert health["status"] == "ok"
    assert health["index"] == {"documents": 0, "chunks": 0}

    response = endpoints["/api/questions"](
        QuestionRequest(question="Come si pulisce il filtro?", include_images=True)
    )
    assert response["sources"] == []
    assert "Non ho trovato" in response["answer"]
