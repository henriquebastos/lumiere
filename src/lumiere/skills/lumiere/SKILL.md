---
name: lumiere
description: "Derive a HyperFrames video's timing from its narration: every scene start, scene length, and gesture inside a frame resolves from a spoken word, so the picture reflows when the narration is re-recorded. Use when starting a video project with Lumiere, when a project has narration parts or words.json files, when timing or sync is wrong, when a scene's narration must be remade, or when anchors, cues, voiceovers, or lumiere commands are involved. For a video with no narration at all, use the HyperFrames workflows directly."
---

# Lumiere

A video whose timing is **derived**, never typed. The narration comes first;
every clip start, clip duration, and gesture inside a frame resolves from a
word that was actually said. Change the words, remake that narration, run the
build: the picture follows.

Read `references/anchoring.md` for the anchor grammar.

## HyperFrames is the source of truth

Lumiere's one job is to adjust a composition's timing from its narration.
Everything it adds to a composition is namespaced so HyperFrames ignores it:

| Lumiere writes | on | HyperFrames reads |
|---|---|---|
| `data-lumiere-words="…/scene.words.json"` | a root or a host | — (owns a narration) |
| `data-lumiere-voiceover="…"` | a host | — (its sentences; anchors default from them) |
| `data-lumiere-start` / `data-lumiere-end` | a timed element | `data-start`, `data-duration` |
| `// @lumiere word:with#1+0.150` | after a GSAP position | the position number |

`lumiere build` reads the left column and writes the right one. A project
must stay a working HyperFrames project with Lumiere removed; Lumiere adapts
to HyperFrames, never the reverse. Studio is the editor; see "Studio" below.

## One rule at every level

An element with `data-lumiere-words` **owns a narration** for everything
below it: its own cues, the hosts it anchors, the voiceovers it defaults, and
its `<audio>`. A host without one resolves against the nearest owner above,
scoped to its own span. Child words win. The film is whatever the top adds
up to.

- On a **host** (`data-composition-src`), `data-lumiere-words` places it after
  the host before it and makes it last as long as its words; its composition
  counts from zero: `word:x` is the first "x" *of that scene*, `film:end` is
  where its narration ends, and its `<audio>` spans it.
- On a **root** (the composition element of a file), it declares the file's
  narration; the root spans it unless it says otherwise.
- `frame:start` / `frame:end` on an element mean this composition's own span,
  for a root that inherits its narration and for exits cued inside a frame.
- Nothing is read that the markup does not name. No folder or file name is
  assumed; the examples below are suggestions, not requirements.

Three shapes, same rule:

```html
<!-- one recording for the whole film -->
<div id="main" data-composition-id="main" data-lumiere-words="narration/film.words.json">
  <audio src="assets/narration.wav" data-lumiere-start="film:start" data-lumiere-end="film:end"></audio>
  <div id="host-a" data-composition-src="compositions/a.html" data-lumiere-voiceover="First sentence."></div>

<!-- each scene owns its narration (preferred for a film built from parts) -->
<div id="host-opening" data-composition-src="compositions/opening.html"
     data-lumiere-words="narration/opening.words.json"
     data-lumiere-voiceover="Every scene starts on the word that opens it."></div>
<!-- compositions/opening.html -->
<audio src="assets/narration/opening.wav" data-lumiere-start="film:start" data-lumiere-end="film:end"></audio>

<!-- a chapter owns its narration; its scenes anchor into it, one scene owns its own -->
<div id="host-ch1" data-composition-src="compositions/ch1.html" data-lumiere-words="narration/ch1.words.json"></div>
<!-- compositions/ch1.html -->
<div id="ch1" data-composition-id="ch1">
  <div id="scene-a" data-composition-src="scenes/a.html" data-lumiere-voiceover="…"></div>
  <div id="scene-b" data-composition-src="scenes/b.html" data-lumiere-words="narration/b.words.json"></div>
```

## Narration is parts

A narration is made of parts - a sentence or a short paragraph each - that
are spoken, adjusted, verified, and joined. Nothing is ever cut: a word
change is a remade part. Each scene (or chapter, or the film) keeps its parts
in one folder with a `sequence.txt` naming them in order and the pause after
each; the last pause is the air before whatever comes next.

```bash
cd narration/opening
lumiere speak -f 03.txt --previous-file 02.txt --next-file 04.txt -o ../../takes/03.wav --lexicon ../../pronunciations.json
lumiere adjust ../../takes/03.wav -o 03.wav --pace 5.2:5.6 --trim --fade --loudness -22.85 --syllables ../../syllables.json
lumiere transcribe 03.wav                                  # -> 03.words.json
lumiere verify 03.wav --pace 5.0:5.6 --match 0.97 --syllables ../../syllables.json   # exit 1 if it drifted
cd ../..
lumiere join -l narration/opening/sequence.txt -o assets/narration/opening.wav --words narration/opening.words.json
lumiere build . && lumiere check .
```

Respellings for names the voice gets wrong go in a JSON file named with
`--lexicon`; syllable counts the dictionary lacks in one named with
`--syllables`. Lumiere reads neither unless named. One lexicon can serve
every part: a part's companion records only the entries its text uses, so a
new entry respeaks only the parts that say that word. `speak --model` picks
the ElevenLabs model (default: `eleven_multilingual_v2`). A video's `package.json`
is the place for its file names and thresholds; keep them there, not in
prose.

## The loop

```bash
lumiere build .      # anchors -> seconds, every level
lumiere check .      # errors: an anchor that cannot be honoured, or stale seconds
                     # warnings: typed seconds; a voiceover that no longer matches its words
```

### Select the HyperFrames CLI

Inspect `package.json` and the project instructions. Use project scripts first.
Choose the first applicable row for each HyperFrames command:

| Project state | Invocation |
| --- | --- |
| A project script provides the command | `pnpm run <script>` with the project's script name, such as `check` or `render` |
| No matching script, but an installed local dependency | `pnpm exec hyperframes <command>` |
| No matching script and no local dependency | `pnpm dlx hyperframes@<version> <command>` |

For dlx, replace `<version>` with the project's explicit version selector.
Use `@latest` only when the project permits latest. Keep existing pins unchanged.
If HyperFrames is declared but not installed, install the project's locked dependencies before using `pnpm exec`.
Do not replace a missing local installation with dlx. dlx resolves an external package and does not use the local dependency.

After selecting the invocation, run `check`, then `render --output out/film.mp4`.
Use this selection for `preview` and `skills update` too.

`build` stops when a cue names a word its narration lacks, naming the file.
That is the design working: re-cue it, or remake the narration.

## Anchoring

Cue the *head* of a gesture to a word and let the rest follow relatively:

```js
tl.fromTo("#tile", {...}, {...}, 0.630);   // @lumiere word:with#1+0.150
tl.fromTo("#w1",   {...}, {...}, "<0.055"); // stagger - not a sync point
tl.to("#tile",     {...},        4.227);   // @lumiere frame:end-0.593
```

Three mistakes to avoid, each learned by making it:

1. **Snapping to a word's start.** Keep the authored offset (`+0.150`), or
   every anticipatory entrance silently re-times.
2. **Anchoring stagger.** Ten letters 55ms apart are one gesture, not ten
   moments. Only the head gets a `@lumiere`.
3. **Anchoring an exit to a word.** An exit belongs to the frame's own length:
   `frame:end-0.593`.

A host usually starts on the first word of its sentence and ends where the
next one begins. Say the sentence on the host as `data-lumiere-voiceover` and
both anchors default from it; explicit `data-lumiere-start` / `-end` win. The
voiceovers are the script: they are aligned in document order against the
owner's words, a word the speaker changed falls forward to the next that
matched, and `check` warns when a voiceover no longer reads as what was said.

## Studio

Studio is the editor. Picture edits (layout, text, style, new elements) are
just edits: `git diff`, `lumiere check .`, commit. Studio also stamps
`data-hf-id` on elements the first time it loads a file; commit those too.

Timing edits are different: Studio writes a second, the build derives it.
After dragging a keyframe or a clip, run `lumiere absorb .` to turn the
difference into offset on the cue (`word:with+0.150` → `word:with+0.630`) or
on the host's anchor; the build then agrees with what the editor saw. A host
that owns its narration cannot be dragged into a different length - change
its parts or its pauses instead. `check` reports the project as stale until
`absorb` or `build` has run.

A tween added in Studio has no cue: `check` warns that it will not move with
the audio. Add `// @lumiere …` when it should.

Open Studio with the project's preview script or selected HyperFrames CLI.
Before launching, follow the command selection in `references/driving-studio.md`.
`agent-browser` drives Studio. Submitted comments arrive via
`lumiere feedback .`, and `--ack` clears them once the revision is done.

## Set up

Lumiere is a uv tool, installed once per machine; a video has no Python of
its own. Skills belong to the video. HyperFrames commands require pnpm and
Node.js 22.13 or newer.

This example starts a new project with no local HyperFrames dependency or existing version policy.
It uses latest for initialization. For an existing project, select the CLI as described above.

```bash
brew install uv node pnpm ffmpeg
uv tool install "lumiere @ git+https://github.com/henriquebastos/lumiere.git"   # or --editable <checkout>
mkdir <slug> && cd <slug> && git init
pnpm dlx hyperframes@latest init .      # the producer picks the workflow
lumiere skills update .                # this skill, under .agents/skills/lumiere/
lumiere adopt .                        # a note in AGENTS.md: seconds here are derived
```

Run `skills update` through the HyperFrames CLI selected above.
If it installs skills into the home directory, copy the HyperFrames skill set into `.agents/skills/` instead.
Write the agent instructions in `AGENTS.md` only; do not add a `CLAUDE.md`.

`speak` and `transcribe` call ElevenLabs. They read
`ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` from the environment only and
refuse in one line when a variable is missing. Lumiere reads no `.env` file.
