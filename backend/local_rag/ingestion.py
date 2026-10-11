"""Shared content checks for the agent's dataset-specific ingestion."""
import hashlib
from .context import text_key


def content_hash(text: str) -> str:
    """Body identity is separate from ancestry-sensitive embedding input hashes."""
    return hashlib.sha256(text_key(text).encode()).hexdigest()


def navigation_only(text: str, known_headings: set[str]) -> bool:
    """Use confirmed headings normalized once with heading_keys, not length."""
    lines=[text_key(line) for line in text.splitlines() if line.strip()]
    return bool(lines) and all(line in known_headings for line in lines)


def heading_keys(headings) -> set[str]:
    return {text_key(heading) for heading in headings}
