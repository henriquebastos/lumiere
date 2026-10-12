# Lumiere

A library and a CLI that derive a video's timing from a recorded narration.
Read `README.md` first. The skill Lumiere ships to video projects is
`src/lumiere/skills/lumiere/SKILL.md`; it is the user-facing guide and must
stay correct when a command changes.

## Boundaries

- Lumiere knows no video. Every command takes an explicit file or project
  directory. Never add a path to a video, a repository root, or a `.env` file;
  `tests/test_boundary.py` fails the package if one appears.
- Credentials come from the environment only. A missing variable is bad input:
  exit 2, one line on stderr naming the variable, nothing written.
- Skills belong to the video. `lumiere skills update <project>` installs them
  under `<project>/.agents/skills/`; nothing is installed globally.
- Agent instructions live in `AGENTS.md` only. Do not create a `CLAUDE.md`.

## Verify

```bash
uv run pytest -q
```

Tests are the specification. A behaviour change needs a test that fails
without it.
