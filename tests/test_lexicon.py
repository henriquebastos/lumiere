"""The pronunciation lexicon.

It must change only what the voice says, never what the script says: anchors
address the script's words, and a respelling that leaked into the project
would corrupt them.
"""

from __future__ import annotations

import json
from pathlib import Path

from lumiere.core.lexicon import apply_lexicon, load_lexicon




def test_the_lexicon_respells_exact_words_and_nothing_else():
    """`Siobhan` must not rewrite a word that merely contains it, and the
    replacement must survive punctuation hugging the word — punctuation is
    how the word appears in real prose."""
    lex = {"Henrique": "En-hee-kee", "Siobhan": "Shiv-awn"}

    assert apply_lexicon("Hi, Henrique here.", lex) == "Hi, En-hee-kee here."
    assert apply_lexicon("Nguyen, Siobhan, Okafor.", lex) == "Nguyen, Shiv-awn, Okafor."
    assert apply_lexicon("Siobhans would not match", lex) == "Siobhans would not match"


def test_a_later_lexicon_overrides_an_earlier_one(tmp_path):
    shared = tmp_path / "repo.json"
    shared.write_text(json.dumps({"Henrique": "wrong", "Siobhan": "Shiv-awn"}))
    local = tmp_path / "project.json"
    local.write_text(json.dumps({"Henrique": "En-hee-kee"}))

    merged = load_lexicon(shared, local)

    assert merged == {"Henrique": "En-hee-kee", "Siobhan": "Shiv-awn"}
