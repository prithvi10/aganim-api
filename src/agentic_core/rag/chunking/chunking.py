import re
from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class Chunk:
    content: str
    chunk_index: int
    oversized: bool = False


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _split_sentences(text: str) -> List[str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return []
    parts = _SENTENCE_RE.split(cleaned)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(
    text: str,
    *,
    max_len: int = 500,
    overlap: int = 50,
) -> List[Chunk]:
    """
    Chunk text into ~max_len character segments with a small overlap.
    Uses sentence boundaries when possible.
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: List[Chunk] = []
    buf: List[str] = []
    buf_len = 0

    def flush(oversized: bool = False):
        nonlocal buf, buf_len
        if not buf:
            return
        content = " ".join(buf).strip()
        if content:
            chunks.append(Chunk(content=content, chunk_index=len(chunks), oversized=oversized))
        buf = []
        buf_len = 0

    for sent in sentences:
        s_len = len(sent)
        if not buf:
            if s_len > max_len:
                chunks.append(Chunk(content=sent, chunk_index=len(chunks), oversized=True))
                continue
            buf.append(sent)
            buf_len = s_len
            continue

        if buf_len + 1 + s_len > max_len:
            flush()
            if overlap > 0 and chunks:
                tail = chunks[-1].content[-overlap:]
                if tail:
                    buf = [tail]
                    buf_len = len(tail)
            if s_len > max_len:
                chunks.append(Chunk(content=sent, chunk_index=len(chunks), oversized=True))
                buf = []
                buf_len = 0
            else:
                buf.append(sent)
                buf_len += s_len
            continue

        buf.append(sent)
        buf_len += 1 + s_len

    flush()
    return chunks


def chunk_many(texts: Iterable[str], *, max_len: int = 500, overlap: int = 50) -> List[Chunk]:
    out: List[Chunk] = []
    for text in texts:
        out.extend(chunk_text(text, max_len=max_len, overlap=overlap))
    return out
