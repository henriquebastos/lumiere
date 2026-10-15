# Driving Studio as an agent

Studio is how a producer reviews a film, so an agent that cannot open it cannot
check its own work. It is a local server and a browser — nothing more.

## Open it

From the project directory, inspect `package.json` and the project instructions.
Use project scripts first. Choose the first applicable row:

| Project state | Preview command |
| --- | --- |
| A project script opens Studio | `pnpm run dev` (use the project's preview script name) |
| No preview script, but an installed local dependency | `pnpm exec hyperframes preview` |
| No preview script and no local dependency | `pnpm dlx hyperframes@<version> preview` |

For dlx, replace `<version>` with the project's explicit version selector.
Use `@latest` only when the project permits latest. Keep existing pins unchanged.
If HyperFrames is declared but not installed, install the project's locked dependencies before using `pnpm exec`.
Do not replace a missing local installation with dlx. dlx resolves an external package and does not use the local dependency.

It watches the project and refreshes as files change, so an agent editing
compositions is visible immediately. That is the whole of the agent → producer
direction; it needs no wiring.

## Drive it

```bash
pnpm add -g agent-browser           # once
agent-browser open http://localhost:3000
agent-browser snapshot -i        # refs are assigned fresh on every snapshot
agent-browser click @e7          # the Storyboard tab
agent-browser snapshot -i
agent-browser fill @e22 "the Harbor tile lands a beat late"
agent-browser click @e7          # "Save & copy message (N)"
```

Read `agent-browser skills get core` before the first command. The skills ship
with the CLI and are version-matched, which is why Lumiere does not vendor a
copy of them.

## What a submission does

Studio writes `.hyperframes/frame-comments.json`, naming each frame and the
file it came from. Then:

```bash
lumiere feedback .          # read them
lumiere feedback . --ack    # delete the batch once the revision is done
```

The deletion is the acknowledgement — Studio re-reads the file when its window
regains focus, so one that is gone reads as "applied" and one that lingers
reads as "never seen".

## Verified

The whole path was exercised on a real project: a comment typed into the
board, written by Studio to the contract file with `"pass": "final"`, read back
by `lumiere feedback` with the frame and its source path, and cleared by
`--ack` — after which Studio no longer showed it pending.


## Concurrent editing caution

Studio's element-edit flow and an agent editing the same frame file can race:
Studio serializes its cached DOM back to disk and can overwrite an agent's
just-written pass with stale markup (observed in practice: a frame's SVG
reverted while its script kept the new values). During heavy revision,
prefer batching Studio comments and letting one side apply changes; after any
suspected race, re-verify the file and rebuild rather than assuming either
version won.
