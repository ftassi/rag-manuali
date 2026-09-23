from test_retrieval import settings_for

from manuali_rag.api import QuestionRequest, _source_payload, create_app
from manuali_rag.store import SearchHit


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


def test_source_page_link_requires_rendered_pdf_page(tmp_path) -> None:
    settings = settings_for(tmp_path)
    hit = SearchHit(
        chunk_id=1,
        document_id="doc1",
        manual_title="Manuale sintetico",
        page=9,
        section="Diagnostica",
        content="Codice R17.",
        image_path="documents/doc1/images/schema.png",
        visual_summary=None,
        score=1.0,
    )

    assert _source_payload(hit, settings)["page_url"] is None

    page_image = tmp_path / "documents" / "doc1" / "pages" / "page-0009.jpg"
    page_image.parent.mkdir(parents=True)
    page_image.touch()

    assert _source_payload(hit, settings)["page_url"] == "/api/documents/doc1/pages/9"
