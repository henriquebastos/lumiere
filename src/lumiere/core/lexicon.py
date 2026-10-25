"""Pronunciation: respellings the voice needs for names it gets wrong.

The respelling goes only into the TTS request; the written text keeps the
true spelling, and anchors address whatever the transcription heard.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def load_lexicon(*paths: Path) -> dict[str, str]:
    """Merge pronunciation lexicons; later paths win.

    The caller names the file(s) with `speak --lexicon`; nothing is read that
    was not named.
    """
    merged: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        entries = json.loads(path.read_text())
        if not isinstance(entries, dict):
            raise ValueError(f"{path}: a lexicon is a JSON object of word -> respelling")
        merged.update(entries)
    return merged


def apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    """Respell lexicon words for the voice, leaving everything else verbatim.

    Matching is exact and case-sensitive on whole words: the entries are
    proper nouns, and `Henrique` must not rewrite a word that merely
    contains it.
    """
    for word, respelling in lexicon.items():
        text = _respell(text, word, respelling)
    return text


def used_entries(text: str, lexicon: dict[str, str]) -> dict[str, str]:
    """The entries that change `text`, in the order `apply_lexicon` applies them.

    Applying only these gives the same request as applying the whole lexicon:
    an entry left out changed nothing at its turn.
    """
    used: dict[str, str] = {}
    for word, respelling in lexicon.items():
        respelled = _respell(text, word, respelling)
        if respelled != text:
            used[word] = respelling
            text = respelled
    return used


def _respell(text: str, word: str, respelling: str) -> str:
    return re.sub(
        rf"(?<!\w){re.escape(word)}(?!\w)", respelling.replace("\\", r"\\"), text
    )
