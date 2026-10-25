"""The `lumiere` entry point.

Argument parsing and exit codes, nothing else. Every decision this module
appears to make was already made by `core`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

import requests

from lumiere.adapters.elevenlabs import TTS_MODEL, MissingApiKey, voice_from_env
from lumiere.cli.build import build, build_composition
from lumiere.cli.check import check
from lumiere.cli.feedback import acknowledge, pending, wait_for
from lumiere.cli.absorb import absorb
from lumiere.cli.adopt import adopt
from lumiere.cli.skills import SKILLS_ROOT, update_skills
from lumiere.cli.adjust import adjust
from lumiere.cli.conventions import (
    EXIT_CHECK_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    count,
    dbtp,
    lufs,
    match_threshold,
    opened,
    pace_target,
    seconds,
    span,
    speech_model,
    speech_speed,
    read_text,
    write_json_line,
    words_path,
)
# Aliased: `cut` below binds `join` as a loop variable.
from lumiere.cli.join import join as join_parts, parts_from_arguments, parts_from_sequence
from lumiere.cli.measure import audio_paths, measure, overrides_from, summarize, text_for
from lumiere.cli.speak import speak
from lumiere.cli.voices import LABELS, add_voice, list_voices
from lumiere.core.lexicon import load_lexicon
from lumiere.cli.transcribe import transcribe_file
from lumiere.core.adjust import Refusal
from lumiere.cli.verify import Requirements, verify
from lumiere.cli.words import words

#: What a provider adapter raises when the request was made and failed.
PROVIDER_FAILURES = (RuntimeError, requests.RequestException)


def _one_line(error: BaseException) -> str:
    return " ".join(str(error).split()) or type(error).__name__


def _refuse_in_one_line(command: argparse.ArgumentParser, message: str) -> NoReturn:
    """Bad input that is not a usage mistake, such as a missing credential:
    exit 2 like `error()`, but one stderr line, without the usage block."""
    command.exit(EXIT_USAGE, f"{command.prog}: error: {message}\n")


def _run(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(
        prog="lumiere", description="Word-anchored video timing."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("adopt", "put a HyperFrames project's timing under Lumiere"),
        ("transcribe", "one audio file into its word timings"),
        ("build", "resolve every anchor into seconds, for the film "
                   "or for one composition against its own word timings"),
        ("words", "print a words file's anchor vocabulary: token#occurrence at time"),
        ("check", "fail if an anchor cannot be honoured or the seconds are stale; "
                  "warn about hand-written seconds"),
        ("absorb", "keep the seconds Studio wrote by moving the anchors they came from"),
        ("feedback", "show the frame comments a producer submitted in Studio"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "project", nargs="?", default=".",
            help="an audio file" if name == "transcribe"
            else "a words file (a.words.json)" if name == "words"
            else "a composition, or a project directory" if name == "build"
            else "project directory",
        )
        if name == "build":
            build_command = command
            command.add_argument(
                "--words", type=Path,
                help="with a composition: the word-timing file its anchors and cues "
                     "resolve against (required with a composition)",
            )
        if name == "transcribe":
            transcribe_command = command
            command.add_argument(
                "-o", "--output", type=Path,
                help="where the word timings go; `-` prints them "
                     "(default: a.words.json beside the audio)",
            )
            command.add_argument(
                "--language",
                help="the spoken language, such as en (default: the provider detects it)",
            )
        if name == "feedback":
            command.add_argument(
                "--wait", action="store_true", help="block until comments arrive"
            )
            command.add_argument(
                "--ack",
                action="store_true",
                help="delete the batch, telling Studio the work is done",
            )

    # The audio primitives take files, not a project directory.
    speak_command = commands.add_parser(
        "speak",
        help="speak one text into one audio file, with one provider request; "
             "skipped when a.wav.json records the same text and settings",
    )
    speak_command.add_argument(
        "text", nargs="?", help="the text to speak; `-` reads it from stdin",
    )
    speak_command.add_argument(
        "-f", "--text-file", type=Path, help="read the text to speak from this file",
    )
    speak_command.add_argument(
        "-o", "--output", type=Path, required=True,
        help="the spoken audio, a .wav file; a.wav.json records how it was made",
    )
    speak_command.add_argument(
        "--voice", help="ElevenLabs voice id (default: ELEVENLABS_VOICE_ID)",
    )
    for side, where in (("previous", "before"), ("next", "after")):
        neighbour = speak_command.add_mutually_exclusive_group()
        neighbour.add_argument(
            f"--{side}", metavar="TEXT",
            help=f"the text spoken {where} this one, sent as context, never spoken",
        )
        neighbour.add_argument(
            f"--{side}-file", type=Path, metavar="FILE",
            help=f"read --{side} from this file",
        )
    speak_command.add_argument(
        "--lexicon", type=Path,
        help="a JSON object of word -> respelling, applied to the request only "
             "(default: none)",
    )
    speak_command.add_argument(
        "--model", type=speech_model, default=TTS_MODEL,
        help=f"ElevenLabs model id (default: {TTS_MODEL})",
    )
    speak_command.add_argument(
        "--speed", type=speech_speed,
        help="how fast the voice speaks, 1 being its own pace (default: the provider's)",
    )
    speak_command.add_argument(
        "--force", action="store_true",
        help="speak again even when a.wav.json records the same text and settings, "
             "and replace audio speak did not make",
    )

    measure_command = commands.add_parser(
        "measure",
        help="print duration, loudness, true peak, pace, and transcript match per audio file",
    )
    measure_command.add_argument(
        "audio", nargs="+", type=Path,
        help="audio files to measure; `-` reads one path per line from stdin",
    )
    measure_command.add_argument(
        "--text-file", type=Path,
        help="the spoken text, for pace; only with exactly one audio file "
             "(default: the `text` recorded in a.wav.json)",
    )
    measure_command.add_argument(
        "--syllables", type=Path, metavar="FILE",
        help="syllable counts for words the dictionary lacks, a JSON object of word to count",
    )
    measure_command.add_argument(
        "--summary", action="store_true",
        help="end with one line of median, min, and max",
    )

    verify_command = commands.add_parser(
        "verify",
        help="check audio files against required pace, loudness, peak, and match, "
             "and against the hash in a.wav.json; exit 1 if any check fails",
    )
    verify_command.add_argument(
        "audio", nargs="+", type=Path,
        help="audio files to check; `-` reads one path per line from stdin",
    )
    verify_command.add_argument(
        "--syllables", type=Path, metavar="FILE",
        help="syllable counts for words the dictionary lacks, a JSON object of word to count",
    )
    verify_command.add_argument(
        "--pace", type=span, metavar="LOW:HIGH",
        help="syllables per second of speech, such as 5.0:5.6",
    )
    verify_command.add_argument(
        "--loudness", type=span, metavar="LOW:HIGH",
        help="integrated loudness in LUFS, such as -24:-21.7",
    )
    verify_command.add_argument(
        "--peak", type=dbtp, metavar="DBTP",
        help="the highest true peak allowed, such as -1",
    )
    verify_command.add_argument(
        "--match", type=match_threshold, metavar="exact|RATIO",
        help="the least transcript match against the text, `exact` or a ratio such as 0.98",
    )
    verify_command.add_argument(
        "--text-file", type=Path,
        help="the spoken text, for --pace and --match; only with exactly one audio file "
             "(default: the `text` recorded in a.wav.json)",
    )
    verify_command.add_argument(
        "--words", type=Path,
        help="the word timings for --match; only with exactly one audio file "
             "(default: a.words.json beside the audio)",
    )
    verify_command.add_argument(
        "--report", type=Path,
        help="also write every file's checks to one JSON file; `-` prints it",
    )

    adjust_command = commands.add_parser(
        "adjust",
        help="bring one audio file to a pace, trim it, fade it, level it; "
             "steps run in that order and are appended to out.wav.json",
    )
    adjust_command.add_argument("audio", type=Path, help="the audio file to adjust")
    adjust_command.add_argument(
        "-o", "--output", type=Path, required=True,
        help="the adjusted audio, a .wav file",
    )
    adjust_command.add_argument(
        "--syllables", type=Path, metavar="FILE",
        help="syllable counts for words the dictionary lacks, a JSON object of word to count",
    )
    adjust_command.add_argument(
        "--pace", type=pace_target, metavar="TARGET|LOW:HIGH",
        help="syllables per second of speech: 5.4 changes the tempo to reach 5.4; "
             "5.2:5.6 leaves a pace inside the range alone and moves one outside "
             "to its middle; refused when that needs a tempo outside 0.85-1.25",
    )
    adjust_command.add_argument(
        "--trim", action="store_true",
        help="cut leading and trailing silence, keeping 60 ms before and 70 ms after",
    )
    adjust_command.add_argument(
        "--fade", action="store_true", help="fade in over 8 ms and out over 12 ms",
    )
    adjust_command.add_argument(
        "--loudness", type=lufs, metavar="LUFS",
        help="apply the gain that reaches this integrated loudness, such as -22.85; "
             "refused when the true peak would pass -1 dBTP (default: no gain)",
    )
    adjust_command.add_argument(
        "--text-file", type=Path,
        help="the spoken text, for --pace; recorded as the output's text "
             "(default: the `text` recorded in a.wav.json)",
    )

    join_command = commands.add_parser(
        "join",
        help="join audio parts into one file, shifting each part's word timings",
    )
    join_command.add_argument(
        "audio", nargs="*", type=Path,
        help="the parts in order, each with its a.words.json beside it",
    )
    join_command.add_argument(
        "-l", "--list", dest="sequence", type=Path,
        help="a sequence file instead of parts: one file per line, then the pause "
             "after it; paths relative to the sequence file; `-` reads stdin",
    )
    join_command.add_argument(
        "--gap", type=seconds,
        help="seconds of silence between parts given as arguments (default 0)",
    )
    join_command.add_argument(
        "-o", "--output", type=Path, required=True,
        help="the joined audio, a .wav file",
    )
    join_command.add_argument(
        "--words", type=Path,
        help="the joined word timings; `-` prints them (default: out.words.json beside -o)",
    )

    voices_command = commands.add_parser(
        "voices",
        help="list the voices that could speak, one JSON line each, "
             "or save a library voice to the account",
    )
    voices_actions = voices_command.add_subparsers(dest="action", required=True)
    voices_list = voices_actions.add_parser(
        "list",
        help="the account's voices; with --library, a search of the ElevenLabs voice library",
    )
    voices_list.add_argument(
        "--library", action="store_true",
        help="search the voice library instead of the account; a voice found there "
             "needs `voices add` before speak can use it",
    )
    voices_list.add_argument(
        "--search", metavar="WORDS",
        help="words such as 'calm narration': in the account, each must occur in the name, "
             "description, or labels; in the library, the provider's own search",
    )
    for label in LABELS:
        voices_list.add_argument(
            f"--{label.replace('_', '-')}", dest=label, metavar="LABEL",
            help=f"only voices whose {label.replace('_', ' ')} label is this, such as "
                 + {"gender": "male", "accent": "american", "age": "middle_aged",
                    "descriptive": "calm", "use_case": "informative_educational",
                    "language": "en"}[label],
        )
    voices_list.add_argument(
        "--limit", type=count, default=30,
        help="at most this many lines; the library gives at most 100 (default: 30)",
    )
    voices_add = voices_actions.add_parser(
        "add", help="save a library voice to the account, so speak --voice can use it",
    )
    voices_add.add_argument("owner_id", help="the owner_id that `voices list --library` printed")
    voices_add.add_argument("voice_id", help="the voice_id that `voices list --library` printed")
    voices_add.add_argument("--name", required=True, help="the voice's name in the account")

    skills_command = commands.add_parser(
        "skills", help="install Lumiere's Agent Skills into a video project",
    )
    skills_actions = skills_command.add_subparsers(dest="action", required=True)
    skills_update = skills_actions.add_parser(
        "update", help=f"write every packaged skill under {SKILLS_ROOT}/, replacing it",
    )
    skills_update.add_argument("project", nargs="?", default=".", help="project directory")

    args = parser.parse_args(argv)

    if args.command == "skills":
        try:
            report = update_skills(Path(args.project))
        except ValueError as bad_input:
            skills_update.error(bad_input.args[0])
        for name in report.installed:
            print(f"installed {SKILLS_ROOT}/{name}")
        return 0

    if args.command == "voices":
        command = voices_list if args.action == "list" else voices_add
        try:
            if args.action == "list":
                records = list_voices(
                    args.library, args.search,
                    {label: getattr(args, label) for label in LABELS if getattr(args, label)},
                    args.limit,
                )
            else:
                added = add_voice(args.owner_id, args.voice_id, args.name)
        except MissingApiKey as missing:
            _refuse_in_one_line(command, _one_line(missing))
        except PROVIDER_FAILURES as failed:
            # The request was made and failed: exit 1, nothing printed on stdout.
            print(f"lumiere voices {args.action}: the provider request failed: {_one_line(failed)}",
                  file=sys.stderr)
            return EXIT_CHECK_FAILED
        if args.action == "add":
            print(added)
            return EXIT_OK
        for record in records:
            write_json_line(record)
        if not records:
            print("no voice matches", file=sys.stderr)
        return EXIT_OK

    if args.command == "speak":
        if (args.text is None) == (args.text_file is None):
            speak_command.error('give the text either as an argument ("-" for stdin) or as -f FILE')
        if args.output.suffix.lower() != ".wav":
            speak_command.error(f"{args.output}: speak writes WAV; name the output .wav")
        if not args.output.parent.is_dir():
            speak_command.error(f"{args.output}: no such directory {args.output.parent}")
        voice = args.voice or voice_from_env()
        if not voice:
            _refuse_in_one_line(speak_command, "give --voice or set ELEVENLABS_VOICE_ID")
        text_file = Path("-") if args.text == "-" else args.text_file
        read_files = [p for p in (text_file, args.previous_file, args.next_file) if p is not None]
        if sum(str(path) == "-" for path in read_files) > 1:
            speak_command.error("only one input can read stdin")
        for path in read_files:
            if str(path) != "-" and not path.is_file():
                speak_command.error(f"{path}: no such file")
        if args.lexicon is not None and not args.lexicon.is_file():
            speak_command.error(f"{args.lexicon}: no such lexicon file")

        def given(literal: str | None, path: Path | None) -> str:
            # A file's closing newline is not speech.
            return (read_text(path) if path is not None else literal or "").strip()

        try:
            text = given(args.text, text_file)
            if not text:
                raise ValueError("the text to speak is empty")
            lexicon = load_lexicon(args.lexicon) if args.lexicon is not None else {}
            if not all(isinstance(respelling, str) for respelling in lexicon.values()):
                raise ValueError(f"{args.lexicon}: a lexicon maps each word to a respelling string")
            spoke = speak(
                text, args.output, voice,
                previous_text=given(args.previous, args.previous_file),
                next_text=given(args.next, args.next_file),
                lexicon=lexicon, speed=args.speed, force=args.force, model=args.model,
            )
        except ValueError as bad_input:
            # Empty or undecodable text, a malformed lexicon or companion,
            # audio speak did not make: bad input, exit 2, nothing requested.
            speak_command.error(bad_input.args[0] if bad_input.args else str(bad_input))
        except MissingApiKey as missing:
            _refuse_in_one_line(speak_command, _one_line(missing))
        except PROVIDER_FAILURES as failed:
            # The request was made and failed: exit 1, nothing written.
            print(f"{args.output}: the provider request failed: {_one_line(failed)}",
                  file=sys.stderr)
            return EXIT_CHECK_FAILED
        except subprocess.CalledProcessError:
            print(f"{args.output}: the provider's answer is not audio ffmpeg can read",
                  file=sys.stderr)
            return EXIT_CHECK_FAILED
        if not spoke:
            print(f"{args.output}: unchanged; its companion records the same text "
                  f"and settings", file=sys.stderr)
        print(args.output)
        return EXIT_OK

    if args.command == "adjust":
        if not args.audio.is_file():
            adjust_command.error(f"{args.audio}: no such audio file")
        if args.output.suffix.lower() != ".wav":
            adjust_command.error(f"{args.output}: adjust writes WAV; name the output .wav")
        if not args.output.parent.is_dir():
            adjust_command.error(f"{args.output}: no such directory {args.output.parent}")
        try:
            adjust(
                args.audio, args.output, pace=args.pace, trim=args.trim, fade=args.fade,
                target_lufs=args.loudness, text_file=args.text_file,
                overrides=overrides_from(args.syllables),
            )
        except Refusal as refusal:
            # The audio was read and a step would harm it: a failed check,
            # exit 1, and nothing written.
            print(f"{args.audio}: {refusal}", file=sys.stderr)
            return EXIT_CHECK_FAILED
        except subprocess.CalledProcessError:
            adjust_command.error(f"{args.audio}: not audio ffmpeg can read")
        except FileNotFoundError as missing:
            adjust_command.error(f"{missing.filename}: no such file")
        except ValueError as bad_input:
            adjust_command.error(bad_input.args[0] if bad_input.args else str(bad_input))
        print(args.output)
        return EXIT_OK

    if args.command == "join":
        if (args.sequence is None) == (not args.audio):
            join_command.error("give the parts either as arguments or as -l SEQUENCE")
        if args.sequence is not None and args.gap is not None:
            join_command.error("--gap goes with parts given as arguments; "
                               "a sequence file gives the pause on each line")
        if args.output.suffix.lower() != ".wav":
            join_command.error(f"{args.output}: join writes WAV; name the output .wav")
        if args.sequence is not None and str(args.sequence) != "-" and not args.sequence.is_file():
            join_command.error(f"{args.sequence}: no such sequence file")
        try:
            parts = (
                parts_from_arguments(args.audio, args.gap or 0.0)
                if args.sequence is None
                else parts_from_sequence(args.sequence)
            )
        except ValueError as bad_line:
            join_command.error(f"{args.sequence}: {bad_line}")
        if not parts:
            join_command.error(f"{args.sequence}: lists no parts")
        for part in parts:
            if not part.audio.is_file():
                join_command.error(f"{part.audio}: no such audio file")
            if not words_path(part.audio).is_file():
                join_command.error(
                    f"{words_path(part.audio)}: no word timings for {part.audio}; "
                    "join shifts them and never transcribes"
                )
        words = args.words if args.words is not None else words_path(args.output)
        # Both destinations are checked before either is written, so a bad
        # --words never leaves the audio behind.
        for destination in (args.output, words):
            if str(destination) != "-" and not Path(destination).parent.is_dir():
                join_command.error(f"{destination}: no such directory {Path(destination).parent}")
        try:
            join_parts(parts, args.output, words)
        except ValueError as bad_input:
            # An unreadable part, a malformed words.json: bad input, exit 2.
            join_command.error(bad_input.args[0] if bad_input.args else str(bad_input))
        except FileNotFoundError as missing:
            join_command.error(f"{missing.filename}: no such file")
        if str(words) != "-":
            print(args.output)
        return 0

    if args.command == "verify":
        paths = audio_paths(args.audio)
        if not paths:
            verify_command.error("no audio files given")
        for option, value in (("--text-file", args.text_file), ("--words", args.words)):
            if value is not None and len(paths) != 1:
                verify_command.error(f"{option} goes with exactly one audio file")
        for path in [*paths, *([args.words] if args.words is not None else [])]:
            if not path.is_file():
                verify_command.error(f"{path}: no such file")
        if (
            args.report is not None and str(args.report) != "-"
            and not args.report.parent.is_dir()
        ):
            verify_command.error(f"{args.report}: no such directory {args.report.parent}")
        required = Requirements(
            pace=args.pace, loudness=args.loudness, peak=args.peak, match=args.match
        )
        records = []
        for path in paths:
            # As in `measure`: unreadable audio or a malformed companion is
            # bad input, exit 2; exit 1 means a check ran and failed.
            try:
                records.append(verify(path, required, args.text_file, args.words, overrides_from(args.syllables)))
            except subprocess.CalledProcessError:
                verify_command.error(f"{path}: not audio ffmpeg can read")
            except FileNotFoundError as missing:
                verify_command.error(f"{missing.filename}: no such file")
            except ValueError as bad_input:
                verify_command.error(bad_input.args[0] if bad_input.args else str(bad_input))
            write_json_line(records[-1])
        passed = all(record["passed"] for record in records)
        if str(args.report) == "-":
            # stdout stays JSON lines: the report is one more line.
            write_json_line({"files": records, "passed": passed})
        elif args.report is not None:
            with opened(args.report) as report:
                report.write(json.dumps({"files": records, "passed": passed}, indent=2) + "\n")
        return EXIT_OK if passed else EXIT_CHECK_FAILED

    if args.command == "measure":
        paths = audio_paths(args.audio)
        if not paths:
            measure_command.error("no audio files given")
        if args.text_file is not None and len(paths) != 1:
            measure_command.error("--text-file goes with exactly one audio file")
        for path in paths:
            if not path.is_file():
                measure_command.error(f"{path}: no such audio file")
        records = []
        for path in paths:
            # A file ffmpeg cannot decode, a text file that is not there, a
            # word with no syllable count, a malformed --syllables file: bad
            # input, so exit 2 like argparse, not 1, which `verify` reserves
            # for a check that failed.
            try:
                records.append(measure(path, text_for(path, args.text_file), overrides_from(args.syllables)))
            except subprocess.CalledProcessError:
                measure_command.error(f"{path}: not audio ffmpeg can read")
            except FileNotFoundError as missing:
                measure_command.error(f"{missing.filename}: no such file")
            except ValueError as bad_input:
                measure_command.error(bad_input.args[0] if bad_input.args else str(bad_input))
            write_json_line(records[-1])
        if args.summary:
            write_json_line(summarize(records))
        return 0

    project = Path(args.project)

    if args.command == "check":
        report = check(project)
        for warning in report.warnings:
            print(f"warning: {warning}")
        for error in report.errors:
            print(f"error: {error}")
        return 0 if report.ok else 1

    if args.command == "absorb":
        try:
            report = absorb(project)
        except (ValueError, KeyError, FileNotFoundError) as refusal:
            _refuse_in_one_line(parser, _one_line(refusal))
        for path, change in report.changes:
            print(f"{path.relative_to(project)}: {change}")
        if not report.changes:
            print("nothing to absorb: the seconds already are what the anchors say")
        return 0

    if args.command == "adopt":
        report = adopt(project)
        for name in report.instructed:
            print(f"noted Lumiere in {name}")
        if not report.instructed:
            print(f"{project}/AGENTS.md already notes Lumiere; nothing to do")
        return 0

    if args.command == "feedback":
        batch = wait_for(project) if args.wait else pending(project)
        if batch is None:
            print("no frame comments pending")
            return 0
        print(f"{len(batch.comments)} comment(s) on the {batch.pass_name} pass:")
        for comment in batch.comments:
            print(comment.describe())
        if args.ack:
            acknowledge(project)
            print("\nacknowledged - Studio will stop showing these as pending")
        return 0

    if args.command == "transcribe":
        if not project.is_file():
            transcribe_command.error(f"{project}: no such audio file")
        output = args.output if args.output is not None else words_path(project)
        if str(output) != "-" and not output.parent.is_dir():
            transcribe_command.error(f"{output}: no such directory {output.parent}")
        try:
            transcribe_file(project, output, language=args.language)
        except subprocess.CalledProcessError:
            transcribe_command.error(f"{project}: not audio ffmpeg can read")
        except ValueError as bad_input:
            transcribe_command.error(bad_input.args[0] if bad_input.args else str(bad_input))
        except MissingApiKey as missing:
            _refuse_in_one_line(transcribe_command, _one_line(missing))
        except PROVIDER_FAILURES as failed:
            # The request was made and failed: exit 1, nothing written.
            print(f"{project}: the provider request failed: {_one_line(failed)}",
                  file=sys.stderr)
            return EXIT_CHECK_FAILED
        if str(output) != "-":
            print(output)
        return EXIT_OK

    if args.command == "words":
        if not project.is_file():
            parser.error(f"{project}: no such words file")
        for line in words(project):
            print(line)
        return 0

    if project.is_file():
        if args.words is None:
            build_command.error(f"{project}: give --words, the word timings it resolves against")
        if not args.words.is_file():
            build_command.error(f"{args.words}: no such word-timing file")
        try:
            report = build_composition(project, args.words)
        except ValueError as bad_input:
            # Malformed words, an anchor naming a word they lack: bad
            # input, exit 2, and the composition is left as it was.
            build_command.error(bad_input.args[0] if bad_input.args else str(bad_input))
        print(project)
        return EXIT_OK
    if args.words is not None:
        build_command.error(
            "--words goes with a composition, not a project directory"
            if project.is_dir() else f"{project}: no such composition"
        )

    report = build(project)
    for path in report.patched:
        print(f"patched {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Turn a refusal into a message.

    Every guard in this system reports by raising - an anchor whose word is
    not in the narration, a stale film. The people running
    these commands do not read Python, and a stack trace makes a clear
    explanation look like a crash.
    """
    try:
        return _run(argv)
    except (ValueError, KeyError, FileNotFoundError) as refusal:
        if isinstance(refusal, FileNotFoundError):
            message = f"{refusal.filename}: not found - is this a Lumiere project directory?"
        else:
            message = refusal.args[0] if refusal.args else str(refusal)
        print(str(message), file=sys.stderr)
        return 1
