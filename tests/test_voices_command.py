"""`lumiere voices` - the voices a caster can choose from, as JSON lines.

A caster compares voices by their labels and descriptions before it spends
anything on speech, so every source gives the same fields. The provider is
replaced everywhere: no test reaches ElevenLabs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from lumiere.adapters import elevenlabs
from lumiere.cli import voices as voices_module
from lumiere.cli.main import main
from lumiere.cli.voices import FIELDS

ACCOUNT = [
    {
        "voice_id": "calm-1", "name": "Ada - Calm Narrator", "category": "professional",
        "description": "Steady and clear, for explainers.", "preview_url": "https://example.test/ada.mp3",
        "labels": {"gender": "female", "accent": "american", "age": "middle_aged",
                   "descriptive": "calm", "use_case": "informative_educational", "language": "en"},
        "sharing": {"public_owner_id": "owner-ada"},
    },
    {
        "voice_id": "loud-2", "name": "Bo - Hype", "category": "premade",
        "description": "Energetic trailer voice.", "preview_url": "https://example.test/bo.mp3",
        "labels": {"gender": "male", "accent": "british", "descriptive": "upbeat",
                   "use_case": "advertisement"},
    },
    {"voice_id": "me-3", "name": "My clone", "category": "cloned", "labels": {"language": "en"}},
]

LIBRARY = [
    {
        "voice_id": "lib-1", "name": "Cy - Unhurried", "public_owner_id": "owner-cy",
        "category": "professional", "gender": "male", "accent": "american", "age": "young",
        "descriptive": "calm", "use_case": "informative_educational", "language": "en",
        "description": "Unhurried teacher.", "preview_url": "https://example.test/cy.mp3",
        "is_added_by_user": False, "cloned_by_count": 42,
    },
]


class FakeProvider:
    """Records each call; answers with the fixed catalogues above."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def account(self, api_key: str) -> list[dict[str, Any]]:
        self.calls.append(("account", (api_key,)))
        return ACCOUNT

    def library(self, api_key: str, filters: dict[str, str], limit: int) -> list[dict[str, Any]]:
        self.calls.append(("library", (api_key, filters, limit)))
        return LIBRARY

    def add(self, api_key: str, owner_id: str, voice_id: str, name: str) -> str:
        self.calls.append(("add", (api_key, owner_id, voice_id, name)))
        return "added-9"


@pytest.fixture
def provider(monkeypatch) -> FakeProvider:
    fake = FakeProvider()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(voices_module, "_default_account_lister", fake.account)
    monkeypatch.setattr(voices_module, "_default_library_searcher", fake.library)
    monkeypatch.setattr(voices_module, "_default_adder", fake.add)
    return fake


def lines(capsys) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_account_voices_print_one_line_each_with_the_same_fields(provider, capsys):
    assert main(["voices", "list"]) == 0
    records = lines(capsys)
    assert [r["voice_id"] for r in records] == ["calm-1", "loud-2", "me-3"]
    assert all(tuple(r) == FIELDS for r in records)
    assert records[0] == {
        "voice_id": "calm-1", "name": "Ada - Calm Narrator", "source": "account",
        "category": "professional", "gender": "female", "accent": "american",
        "age": "middle_aged", "descriptive": "calm", "use_case": "informative_educational",
        "language": "en", "description": "Steady and clear, for explainers.",
        "preview_url": "https://example.test/ada.mp3", "owner_id": "owner-ada",
        "in_account": True, "cloned_by_count": None,
    }
    # A clone has almost no labels; the missing ones are null, not absent.
    assert records[2]["accent"] is None and records[2]["category"] == "cloned"


def test_account_labels_match_whole_and_search_words_all_occur(provider, capsys):
    assert main(["voices", "list", "--descriptive", "CALM", "--use-case", "informative-educational"]) == 0
    assert [r["voice_id"] for r in lines(capsys)] == ["calm-1"]
    assert main(["voices", "list", "--search", "clear explainers"]) == 0
    assert [r["voice_id"] for r in lines(capsys)] == ["calm-1"]
    assert main(["voices", "list", "--accent", "british", "--search", "trailer"]) == 0
    assert [r["voice_id"] for r in lines(capsys)] == ["loud-2"]
    # A label matches whole; a search word may be part of a longer word.
    assert main(["voices", "list", "--descriptive", "cal"]) == 0
    assert lines(capsys) == []
    assert main(["voices", "list", "--search", "narr"]) == 0
    assert [r["voice_id"] for r in lines(capsys)] == ["calm-1"]


def test_no_match_prints_nothing_on_stdout_and_says_so(provider, capsys):
    assert main(["voices", "list", "--gender", "robot"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no voice matches" in captured.err


def test_limit_cuts_the_list(provider, capsys):
    assert main(["voices", "list", "--limit", "2"]) == 0
    assert len(lines(capsys)) == 2


def test_the_library_gets_the_filters_and_marks_voices_not_in_the_account(provider, capsys):
    assert main(["voices", "list", "--library", "--search", "calm", "--gender", "male",
                 "--use-case", "informative_educational", "--limit", "5"]) == 0
    assert provider.calls == [
        ("library", ("test-key", {"search": "calm", "gender": "male",
                                  "use_case": "informative_educational"}, 5)),
    ]
    (record,) = lines(capsys)
    assert record["source"] == "library"
    assert record["owner_id"] == "owner-cy" and record["in_account"] is False
    assert record["cloned_by_count"] == 42 and record["descriptive"] == "calm"


def test_add_saves_a_library_voice_and_prints_its_account_id(provider, capsys):
    assert main(["voices", "add", "owner-cy", "lib-1", "--name", "Cy"]) == 0
    assert provider.calls == [("add", ("test-key", "owner-cy", "lib-1", "Cy"))]
    assert capsys.readouterr().out == "added-9\n"


def test_add_needs_a_name(provider, capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["voices", "add", "owner-cy", "lib-1"])
    assert stopped.value.code == 2
    assert provider.calls == []


@pytest.mark.parametrize("argv", [["voices", "list"], ["voices", "add", "o", "v", "--name", "n"]])
def test_a_missing_api_key_is_one_line_exit_2_and_no_request(provider, monkeypatch, capsys, argv):
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    with pytest.raises(SystemExit) as stopped:
        main(argv)
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1 and "ELEVENLABS_API_KEY" in captured.err
    assert provider.calls == []


def test_a_failed_request_is_one_line_exit_1(provider, monkeypatch, capsys):
    def refuse(api_key: str) -> list[dict[str, Any]]:
        raise RuntimeError("ElevenLabs returned 401: bad key")

    monkeypatch.setattr(voices_module, "_default_account_lister", refuse)
    assert main(["voices", "list"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1 and "401" in captured.err


def test_a_limit_below_one_is_a_usage_error(provider):
    with pytest.raises(SystemExit) as stopped:
        main(["voices", "list", "--limit", "0"])
    assert stopped.value.code == 2


# -- the adapter: requests, not fakes of this module ----------------------


class Response:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.payload, self.status_code, self.text = payload, status, json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self.payload


def test_account_voices_follow_every_page(monkeypatch):
    pages = [
        {"voices": [{"voice_id": "a"}], "has_more": True, "next_page_token": "t2"},
        {"voices": [{"voice_id": "b"}], "has_more": False, "next_page_token": None},
    ]
    seen: list[dict[str, Any]] = []

    def get(url, headers, params, timeout):
        seen.append(dict(params))
        return Response(pages[len(seen) - 1])

    monkeypatch.setattr(requests, "get", get)
    assert [v["voice_id"] for v in elevenlabs.account_voices("k")] == ["a", "b"]
    assert seen == [{"page_size": 100}, {"page_size": 100, "next_page_token": "t2"}]


def test_library_search_sends_the_provider_parameter_names(monkeypatch):
    seen: list[tuple[str, dict[str, Any]]] = []

    def get(url, headers, params, timeout):
        seen.append((url, dict(params)))
        return Response({"voices": [{"voice_id": str(n)} for n in range(10)]})

    monkeypatch.setattr(requests, "get", get)
    found = elevenlabs.library_voices(
        "k", {"search": "calm", "descriptive": "calm", "use_case": "narrative_story", "age": ""}, 3,
    )
    assert len(found) == 3
    assert seen == [(elevenlabs.LIBRARY_URL, {"page_size": 3, "search": "calm",
                                               "descriptives": "calm", "use_cases": "narrative_story"})]


def test_add_posts_the_name_to_the_owner_and_voice(monkeypatch):
    seen: list[tuple[str, dict[str, Any]]] = []

    def post(url, headers, json, timeout):
        seen.append((url, json))
        return Response({"voice_id": "new-id"})

    monkeypatch.setattr(requests, "post", post)
    assert elevenlabs.add_library_voice("k", "owner", "voice", "Cy") == "new-id"
    assert seen == [(f"{elevenlabs.ADD_VOICE_URL}/owner/voice", {"new_name": "Cy"})]


def test_a_provider_error_status_raises(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, headers, params, timeout: Response({"detail": "no"}, 401))
    with pytest.raises(RuntimeError, match="401"):
        elevenlabs.account_voices("k")
