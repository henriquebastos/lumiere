"""`lumiere voices` - the voices that could speak a narration, one JSON line each.

`list` reads the account's voices: premade ones, clones, and library voices
saved to it. `list --library` searches the ElevenLabs voice library instead.
Every line has the same fields, whatever the source: the name, the labels a
caster compares (gender, accent, age, descriptive, use case, language), the
description, and a preview link. A script can choose from these lines without
listening, and a person can listen to the previews later.

`speak --voice` speaks with an account voice. `add` saves a library voice to
the account first; the provider charges nothing for that.
"""

from __future__ import annotations

from typing import Any, Callable

#: The fields of every line, in order.
FIELDS = (
    "voice_id", "name", "source", "category", "gender", "accent", "age", "descriptive",
    "use_case", "language", "description", "preview_url", "owner_id", "in_account",
    "cloned_by_count",
)

#: The label filters `list` takes, matched whole and without regard to case.
LABELS = ("gender", "accent", "age", "descriptive", "use_case", "language")

#: Given the API key, the account's voices in the provider's shape.
AccountLister = Callable[[str], list[dict[str, Any]]]
#: Given the API key, the filters, and a limit, library voices in the provider's shape.
LibrarySearcher = Callable[[str, dict[str, str], int], list[dict[str, Any]]]
#: Given the API key, owner id, voice id, and name, the voice id in the account.
Adder = Callable[[str, str, str, str], str]


def _api_key() -> str:
    from lumiere.adapters.elevenlabs import load_api_key

    return load_api_key()


def _default_account_lister(api_key: str) -> list[dict[str, Any]]:
    from lumiere.adapters.elevenlabs import account_voices

    return account_voices(api_key)


def _default_library_searcher(api_key: str, filters: dict[str, str], limit: int) -> list[dict[str, Any]]:
    from lumiere.adapters.elevenlabs import library_voices

    return library_voices(api_key, filters, limit)


def _default_adder(api_key: str, owner_id: str, voice_id: str, name: str) -> str:
    from lumiere.adapters.elevenlabs import add_library_voice

    return add_library_voice(api_key, owner_id, voice_id, name)


def account_record(raw: dict[str, Any]) -> dict[str, Any]:
    """One account voice as a line. Its labels sit under `labels`."""
    labels = raw.get("labels") or {}
    sharing = raw.get("sharing") or {}
    record = {field: None for field in FIELDS}
    record.update(
        {label: labels.get(label) for label in LABELS},
        voice_id=raw.get("voice_id"),
        name=raw.get("name"),
        source="account",
        category=raw.get("category"),
        description=raw.get("description"),
        preview_url=raw.get("preview_url"),
        owner_id=sharing.get("public_owner_id"),
        in_account=True,
    )
    return record


def library_record(raw: dict[str, Any]) -> dict[str, Any]:
    """One library voice as a line. Its labels are top-level fields."""
    record = {field: None for field in FIELDS}
    record.update(
        {label: raw.get(label) for label in LABELS},
        voice_id=raw.get("voice_id"),
        name=raw.get("name"),
        source="library",
        category=raw.get("category"),
        description=raw.get("description"),
        preview_url=raw.get("preview_url"),
        owner_id=raw.get("public_owner_id"),
        in_account=bool(raw.get("is_added_by_user")),
        cloned_by_count=raw.get("cloned_by_count"),
    )
    return record


def _folded(value: Any) -> str:
    return str(value or "").casefold().replace("-", "_").replace(" ", "_")


def matches(record: dict[str, Any], search: str | None, filters: dict[str, str]) -> bool:
    """True when every given label equals the record's, and every search word
    occurs in its name, description, or labels; case and `-`/`_`/space alike."""
    for label, wanted in filters.items():
        if wanted and _folded(record.get(label)) != _folded(wanted):
            return False
    haystack = _folded(" ".join(
        str(record.get(field) or "") for field in ("name", "description", "category", *LABELS)
    ))
    return all(_folded(word) in haystack for word in (search or "").split())


def list_voices(
    library: bool,
    search: str | None,
    filters: dict[str, str],
    limit: int,
    account_lister: AccountLister | None = None,
    library_searcher: LibrarySearcher | None = None,
) -> list[dict[str, Any]]:
    """At most `limit` lines. The account is filtered here; the library is
    searched by the provider, which matches the same filters itself."""
    api_key = _api_key()
    if library:
        raw = (library_searcher or _default_library_searcher)(
            api_key, {"search": search or "", **filters}, limit
        )
        return [library_record(voice) for voice in raw][:limit]
    records = [account_record(voice) for voice in (account_lister or _default_account_lister)(api_key)]
    return [record for record in records if matches(record, search, filters)][:limit]


def add_voice(owner_id: str, voice_id: str, name: str, adder: Adder | None = None) -> str:
    """Save a library voice to the account; the id `speak --voice` takes."""
    return (adder or _default_adder)(_api_key(), owner_id, voice_id, name)
