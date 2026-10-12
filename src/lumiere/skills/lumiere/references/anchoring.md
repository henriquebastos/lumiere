# Anchoring: timing that comes from the narration

How a Lumiere project's timing works, and the rules that keep it honest. A
project adopted with `lumiere adopt` points here from its own `AGENTS.md`.

## The inversion

`faceless-explainer` plans frames and then writes narration to fit them. This
project runs the other way: **the narration exists first, and the frames are
measured from it.** Substitute its Step 3 / 3.1 with Lumiere's loop (see
`SKILL.md`: parts are spoken, adjusted, verified, joined; `build` turns
anchors into seconds; `check` keeps them honest). Every other step of that
workflow applies unchanged.

A frame's `duration` in `STORYBOARD.md` is a **measurement of the delivery**,
not an estimate. Take it from the narration rather than choosing it.

## Anchors, not seconds

No time in a composition is written by hand. `lumiere check` warns about
every typed second (valid HyperFrames, but it will not move with the audio)
and fails only when an anchor cannot be honoured or the seconds on disk are
not what the anchors resolve to.

```html
<div id="harbor-tile" data-lumiere-start="word:Harbor#2" data-lumiere-end="word:fine.end+0.2">
```

Inside a frame, cue the motion in a comment beside the tween:

```js
tl.fromTo("#tile", {opacity:0}, {opacity:1, duration:0.5}, 0.630);  // @lumiere word:with#1+0.150
tl.to("#tile", {opacity:0, duration:0.5}, 4.227);                   // @lumiere frame:end-0.593
tl.fromTo("#w1", {y:20}, {y:0, duration:0.4}, "<0.055");            // stagger, relative
```

| Kind | Use it for |
| --- | --- |
| `word:X#n.edge±off` | a moment in the speech |
| `film:start` / `film:end±off` | the whole finished piece; `film:end+2.0` holds the picture past the last word — the breath a close needs |
| `frame:start` / `frame:end±off` | this frame's own span — exits belong here |
| `"<0.055"` | stagger inside one gesture, not a sync point |

Preserve the authored offset when you anchor existing motion. Snapping a
gesture to a word's start silently re-times every anticipatory entrance.

A scene host usually starts on the first word of its sentence and ends where
the next one begins. Say the sentence on the host and both anchors default
from it; explicit `data-lumiere-start` / `data-lumiere-end` win when present:

```html
<div id="host-opening" data-composition-src="compositions/opening.html"
     data-lumiere-voiceover="Every scene starts on the word that opens it.">
```

The voiceovers are the script, aligned in document order against the
recording, so a word the speaker changed falls forward to the next one that
matched. The last voiceover ends at `film:end`.

Three resolution rules worth knowing when writing anchors:

- **Words match by their letters.** Case and punctuation are ignored, so
  `word:But`, `word:but` and `word:but,` name the same word — and occurrence
  numbers count over the normalized matches.
- **Frame cues count occurrences inside their own scene.** `word:And#1` in a
  frame is that scene's first "And". Anchors in `index.html` (clip
  boundaries) count globally over the whole take.
- **Offsets are seconds of the narration.** `word:Harbor-0.2` is 200ms before
  Harbor in the audio the scene plays.

## Authoring constraints the cue patcher imposes

`lumiere build` rewrites the number in `tl.xxx(..., N);  // @lumiere ...` by
regex, so a cued tween call must sit on **one line with no semicolons inside
its arguments**. A packet's `onUpdate` must therefore be a **named function**
defined above the timeline, never an inline body. String positions (`"<0.05"`,
`">"`) are relative and need no cue; every numeric position needs one.

## One rule that bites silently

**Words are regenerated, never edited.** A scene's `words.json` comes from
`join`, and each part's from `transcribe`; anchors address words as the
transcription spelled them. Remake the part and re-join rather than editing
a words file, and expect a re-spoken part to spell a name differently
(`Enhiki`, `Enheqi`): `build` names the cue that no longer resolves.

## Review

`npx hyperframes preview` opens the board. `lumiere feedback .` reads what was
submitted, and `--ack` clears it once the revision is done. See
`references/driving-studio.md`.

## Generated narration

### 1 Develop the delivery before anchoring

Generate, transcribe, and assess each candidate before asking the producer
for a listening approval. Compare independently recognized words with the
script and inspect sentence rates, word timings, pauses, and emphasis at
the important ideas. A whole-file word count divided by duration cannot
detect a rushed sentence inside an otherwise slow paragraph.

For pace comparisons, prefer estimated syllables per second to words per
minute. Record both speech rate including pauses and articulation rate
excluding measured longer pauses. State how syllables and pauses were
estimated; dictionary syllables are not acoustic phoneme recognition. Use
clear passages from the same narrator as pace references. Long technical
words can make word-based targets slow the delivery unnecessarily.

Inspect waveform continuity at every assembly boundary. Decode source
audio to PCM, use short edge fades, keep a lossless master, and encode the
listening copy once. Passing a decode check does not establish that joins
are click-free. Measure endpoint discontinuities before and after the fix.

Revise wording, split generation units, adjust supported provider controls,
or edit pauses when the measurements and narrative purpose warrant it.
Generate and assess the affected MP3 again. Preserve candidates and cache
their QA transcripts by audio identity. The producer's listening is final
creative approval, not a prerequisite for the agent's analysis.

Once a part's words are the timing source, keep that audio and its words
stable; a later revision is a new part with its own words, and the affected
cues are rebuilt against it.

A proven setting: short paragraphs and sentence-boundary splits, at most 40
words per request, with neighboring context. Prefer it over the historical
chapter-generation observations below.

### 2 Pronunciation and re-spoken parts

Pronunciation lives in a JSON object of word to respelling
(`Henrique -> En-hee-kee`) named with `speak --lexicon`; it accumulates as
the voice mispronounces names. The respelling goes only into the TTS request
— the script keeps the true spelling, and anchors address whatever the
transcription heard (`Enhiki`, as it happens).

A regenerated narration is a new spine. Scene-scoped cues and normalized
word matching are what make the rebuild cheap - across two full regenerations
of a film's narration, each rebuild cost one or two cue edits, always loudly
named by the build. Expect exactly this churn: the ASR respelling of a
lexicon-corrected name drifts per take (`Enhiki`, `Enheqi`), and token
merging can change (`SRC, dashboard` one take, `src/dashboard,` the next -
the merged path tokens anchor better). Fix what the build names; done.
