# Lumiere

Derive a video's timing from its narration.

Every timed thing on screen is anchored to a **word that was actually said**.
Remake a scene's narration and the film reflows around it: the scene lasts as
long as its new audio, the scenes after it move, and the motion inside each
frame follows the words it belongs to. No time in the composition is written
by hand.

Lumiere renders through [HyperFrames](https://github.com/heygen-com/hyperframes).
HyperFrames owns the compositions, Studio, and the renderer; Lumiere owns the
seconds. Everything Lumiere adds to a composition is namespaced
(`data-lumiere-*`, `// @lumiere`) so HyperFrames ignores it, and a project
stays a working HyperFrames project with Lumiere removed.

`lumiere watch` and `lumiere bundle` play the finished film outside Studio:
served from the project, or as one HTML file with its media embedded.

## Install

Lumiere is a library and a CLI, installed once per machine as a uv tool. Each
video is its own repository that uses it, the way it uses HyperFrames. The
machine needs `uv`, Node.js 22.13 or newer, `pnpm`, and `ffmpeg`:

```bash
brew install uv node pnpm ffmpeg
uv tool install "lumiere @ git+https://github.com/henriquebastos/lumiere.git"
uv tool upgrade lumiere                # later, to follow the newest Lumiere
```

From a checkout, `uv tool install --editable <path>` makes source changes
live. `lumiere` is then on the PATH; a video uses it only through the CLI and
has no virtual environment of its own.

In a new directory with no local HyperFrames dependency or existing version policy,
use latest for initialization:

```bash
git init
pnpm dlx hyperframes@latest init .      # pick the workflow that fits the video
lumiere skills update .                # the lumiere skill, under .agents/skills/
lumiere adopt .                        # a note in AGENTS.md: seconds here are derived
```

`adopt` appends a short note to the `AGENTS.md` HyperFrames already wrote, so
the project's own agent knows its seconds are derived. Everything else it
leaves alone. Open an agent session in the video
and the `lumiere` skill drives the rest.

Lumiere knows nothing about any video and assumes no layout. Every command
takes the files it works on, or reads the ones the markup names; folder and
file names in this README are suggestions, not requirements.

## One rule

An element with `data-lumiere-words` **owns a narration** for everything
below it. A host without one resolves against the nearest owner above, scoped
to its own span. Child words win.

```html
<!-- index.html: each scene owns its narration -->
<div id="main" data-composition-id="main" data-lumiere-start="film:start" data-lumiere-end="film:end">
  <div class="clip" id="host-opening" data-composition-src="compositions/opening.html"
       data-lumiere-words="narration/opening.words.json"
       data-lumiere-voiceover="Every scene starts on the word that opens it."></div>
  <div class="clip" id="host-detail" data-composition-src="compositions/detail.html"
       data-lumiere-words="narration/detail.words.json"
       data-lumiere-voiceover="Its motion follows the words it belongs to…"></div>
</div>

<!-- compositions/opening.html: counts from its own zero -->
<div id="opening-root" data-composition-id="opening" data-lumiere-start="film:start" data-lumiere-end="film:end">
  <audio src="assets/narration/opening.wav" data-lumiere-start="film:start" data-lumiere-end="film:end"></audio>
  …
</div>
<script>
tl.fromTo("#opening-title", {...}, {...}, 0.960);   // @lumiere word:scene
tl.to("#opening-canvas", {...},        4.167);   // @lumiere frame:end
</script>
```

A host with `data-lumiere-words` starts where the host before it ends and
lasts as long as its words; `film:end` inside its composition is where its
narration ends; `word:x` is the first "x" *of that scene*. The film is the
scenes added up.

The same rule gives the other shapes: one recording for the whole film
(`data-lumiere-words` on the root), or a chapter that owns a narration its scenes anchor into
while one scene owns its own. Three levels, one walk.

## Narration is parts

A narration is parts - a sentence or a short paragraph each - spoken,
adjusted, verified, and joined. Nothing is cut: a word change is a remade
part. Each scene keeps its parts in a folder with a `sequence.txt` naming
them in order and the pause after each; the last pause is the air before the
next scene.

```bash
cd narration/opening
lumiere speak -f 03.txt --previous-file 02.txt --next-file 04.txt -o ../../takes/03.wav
lumiere adjust ../../takes/03.wav -o 03.wav --pace 5.2:5.6 --trim --fade --loudness -22.85 --syllables ../../syllables.json
lumiere transcribe 03.wav                                   # -> 03.words.json
lumiere verify 03.wav --pace 5.0:5.6 --match 0.97 --syllables ../../syllables.json   # exit 1 if it drifted
cd ../..
lumiere join -l narration/opening/sequence.txt -o assets/narration/opening.wav --words narration/opening.words.json
lumiere build . && lumiere check .
```

`measure` prints a part's duration, loudness, true peak, pace, and transcript
match; `verify` turns thresholds into an exit code. Respellings for names the
voice gets wrong go in a JSON file named with `speak --lexicon`; syllable
counts the dictionary lacks in one named with `--syllables`. Nothing is read
unless named. One lexicon can serve every part: a part's companion records
only the entries its text uses, so a new entry respeaks only the parts that
say that word. `speak --model` picks the ElevenLabs model
(default: `eleven_multilingual_v2`).

`speak --voice` picks the voice (default: `ELEVENLABS_VOICE_ID`). `voices
list` prints the account's voices, one JSON line each, with the labels a
caster compares: gender, accent, age, descriptive, use case, language, a
description, and a preview link. `--library` searches the ElevenLabs voice
library instead, and `voices add OWNER VOICE --name NAME` saves a library voice
to the account so `speak --voice` can use it. Listing and adding cost nothing.

```bash
lumiere voices list --use-case informative_educational --descriptive calm
lumiere voices list --library --search "calm narration" --language en --limit 10
```

## The loop

```bash
lumiere build .                 # anchors -> seconds, at every level
lumiere check .                 # errors: an anchor that cannot be honoured, or stale seconds
                                # warnings: typed seconds; a voiceover that no longer matches
```

For HyperFrames, inspect `package.json` and the project instructions. Use project scripts first.
Choose the first applicable row for each command:

| Project state | Check and render commands |
| --- | --- |
| Project scripts provide the commands | `pnpm run check` and `pnpm run render --output out/film.mp4` (use the project's script names) |
| No matching script, but an installed local dependency | `pnpm exec hyperframes check` and `pnpm exec hyperframes render --output out/film.mp4` |
| No matching script and no local dependency | `pnpm dlx hyperframes@<version> check` and `pnpm dlx hyperframes@<version> render --output out/film.mp4` |

For dlx, replace `<version>` with the project's explicit version selector.
Use `@latest` only when the project permits latest. Keep existing pins unchanged.
If the project declares HyperFrames but it is not installed, install its locked dependencies before using `pnpm exec`.
Do not replace a missing local installation with dlx. dlx resolves an external package and does not use the local dependency.

## Anchors

A timed element says *when* it happens, never *at what second*.

| Written | Means |
| --- | --- |
| `word:Harbor` | the first "Harbor" in this narration (in this scene, inside a frame) |
| `word:Harbor#2` | the second one (counting from 1) |
| `word:Harbor.end` / `.mid` | where the word finishes / halfway through it |
| `word:Harbor-0.2` | 200ms of breathing before it starts |
| `film:start` / `film:end+2.0` | the narration this element belongs to; `+2.0` holds past its last word |
| `frame:start` / `frame:end-0.5` | this composition's own span - a root that inherits its narration, an exit |

Inside a frame, motion is cued in a comment next to the tween it moves. The
numbers are regenerated by `lumiere build`; the cues are what you edit.
`"<0.055"` is GSAP's own relative syntax, for a stagger inside one gesture
rather than a sync point.

A host usually starts on the first word of its sentence and ends where the
next begins. Say the sentence on the host as `data-lumiere-voiceover` and both
anchors default from it; explicit `data-lumiere-start` / `-end` win. The
voiceovers are the script, aligned against the owner's words, so a word the
speaker changed falls forward to the next that matched.

## Studio

Studio is the editor. Picture edits are edits: `git diff`, `lumiere check .`,
commit. Studio stamps `data-hf-id` on elements the first time it loads a
file; commit those too.

Timing edits are different: Studio writes a second, the build derives it.
After dragging a keyframe or a clip, `lumiere absorb .` turns the difference
into offset on the cue or on the host's anchor, and the build then agrees with
what the editor saw. `check` reports the project as stale until `absorb` or
`build` has run. A host that owns its narration cannot be dragged into a
different length: change its parts or its pauses.

Leave comments on frames in Studio and read them back:

```bash
lumiere feedback .            # what was submitted, and which file each frame is
lumiere feedback . --wait     # block until something is submitted
lumiere feedback . --ack      # delete the batch once the work is done
```

## Watch and bundle

Play the film outside Studio, with no editing tools. Both use HyperFrames' own
bundler (`@hyperframes/core/compiler`) and player (`@hyperframes/player`), so
the page holds the same compositions and clips at the same seconds as Studio
and the render.

```bash
lumiere watch .                       # http://127.0.0.1:8765/ - reload after an edit, Ctrl-C stops
lumiere bundle . -o film.html         # one file that plays anywhere, media embedded
lumiere bundle . -o film.html --audio copy   # keep the original audio bytes
```

`watch` bundles the project again on every reload and reads media from the
project's files. It writes nothing. `bundle` embeds every audio, video, and
image file the film links. The file of an `<audio>` becomes Opus at 32 kbps
unless `--audio copy` keeps it; every other file is copied. A link to a file
that is missing or outside the project is refused, and nothing is written. The
bundler's own notes, such as a font too large to inline, go to stderr.

The HyperFrames version is the project's installed `hyperframes`, else an exact
version in `package.json`; give `--hyperframes VERSION` when it has neither.
Packages the project has not installed go to a temporary directory, through
pnpm (or npm), and are deleted after the command.

Known limit: when a browser blocks sound inside the player's frame, as on
phones, the player plays the audio from the page itself. That copy starts the
audio of a nested scene at the film's start, so scenes after the first can be
silent. Desktop Chrome plays the frame's own audio and is not affected. The fix
belongs in `@hyperframes/player`.

## A project

```text
<slug>/
  index.html        the film: hosts, each naming its scene's words and sentences
  compositions/     the scenes, each with its own <audio> and its cues
  narration/<scene>/  NN.txt NN.wav NN.wav.json NN.words.json sequence.txt
  narration/<scene>.words.json   the scene's joined words   (committed)
  assets/narration/<scene>.wav   the scene's joined audio   (local)
  pronunciations.json  syllables.json   named on the command line, never assumed
  .agents/skills/   the lumiere and HyperFrames skills, installed per project
```

## Credentials

`speak`, `transcribe`, and `voices` call ElevenLabs. They read
`ELEVENLABS_API_KEY`, and `speak` without `--voice` reads `ELEVENLABS_VOICE_ID`,
from the environment only, and refuse in one line when a variable is missing. Supply them from your shell
(direnv, a secrets manager, CI); Lumiere reads no `.env` file. `watch` and
`bundle` reach the network only to install HyperFrames packages the project has
not installed. Nothing else needs the network.

## Working on Lumiere itself

```bash
uv sync --extra dev
uv run pytest -q
```

Tests are the specification: each says *why* the behaviour matters, not just
what it does. `tests/test_boundary.py` keeps the package from naming a video, a
repository root, or a `.env` file. To develop Lumiere beside a video, install
the checkout as the tool: `uv tool install --editable .` from this directory.

### pnpm migration validation

The migration passed all 313 tests with `uv run pytest -q`.
`tests/test_skills_command.py` checks the packaged instructions and installed skill copies.
The tests guard script preference, local CLI selection, explicit external selectors, and preservation of the project's version policy.
These instruction checks do not certify rendering or install global tools.
