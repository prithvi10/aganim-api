from src.main.rag.chunking import chunk_text


def test_chunk_text_overlap():
    text = "Sentence one. Sentence two. Sentence three. Sentence four."
    chunks = chunk_text(text, max_len=25, overlap=5)
    assert len(chunks) >= 2
    first = chunks[0].content
    second = chunks[1].content
    last_word = first.strip().split()[-1]
    assert last_word in second
