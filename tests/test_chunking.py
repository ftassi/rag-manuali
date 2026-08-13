from manuali_rag.chunking import chunk_text


def test_chunk_text_preserves_content_and_limits_size() -> None:
    text = "\n\n".join(f"Paragrafo {index} con alcune parole tecniche." for index in range(20))
    chunks = chunk_text(text, max_chars=180, overlap_chars=30)
    assert len(chunks) > 1
    assert all(len(chunk) <= 220 for chunk in chunks)
    assert "Paragrafo 0" in chunks[0]
    assert "Paragrafo 19" in chunks[-1]


def test_empty_text_has_no_chunks() -> None:
    assert chunk_text("  \n ", max_chars=100, overlap_chars=10) == []
