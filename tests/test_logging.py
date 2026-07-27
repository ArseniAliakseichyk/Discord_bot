"""Log-relay batching."""

from __future__ import annotations

from utils.logging import _CHUNK_LIMIT, _split_lines


class TestSplitLines:
    def test_no_lines_produces_no_messages(self) -> None:
        assert _split_lines([]) == []

    def test_short_lines_are_batched_together(self) -> None:
        chunks = _split_lines(["a", "b", "c"])
        assert chunks == ["a\nb\nc\n"]

    def test_batches_are_split_at_the_limit(self) -> None:
        line = "x" * 100
        chunks = _split_lines([line] * 40, limit=500)
        assert all(len(c) <= 500 for c in chunks)
        assert sum(c.count("x") for c in chunks) == 4000

    def test_never_emits_an_empty_chunk(self) -> None:
        """Regression: an oversized line used to trigger a send of "" first."""
        oversized = "y" * (_CHUNK_LIMIT + 500)
        chunks = _split_lines(["short", oversized, "tail"])
        assert all(chunk.strip() for chunk in chunks)

    def test_an_oversized_line_is_split_and_kept_whole(self) -> None:
        oversized = "z" * 4000
        chunks = _split_lines([oversized], limit=1000)
        assert len(chunks) == 4
        assert "".join(chunks) == oversized

    def test_oversized_line_does_not_swallow_the_pending_batch(self) -> None:
        chunks = _split_lines(["keep-me", "w" * 2000], limit=1000)
        assert chunks[0] == "keep-me\n"
