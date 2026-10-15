"""Generate travel vocabulary recordings with free Edge speech voices."""
import argparse
import asyncio
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parent


def read_words(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"target_language", "pronunciation", "english", "priority"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain: " + ", ".join(sorted(required)))
        words = []
        for line, row in enumerate(reader, 2):
            if not any(row.values()):
                continue
            if None in row or any(row.get(key) is None for key in required):
                raise ValueError(f"CSV line {line}: wrong number of columns")
            row = {key: value.strip() for key, value in row.items()}
            if not row["target_language"] or not row["english"]:
                raise ValueError(f"CSV line {line}: target_language and english are required")
            try:
                row["priority"] = int(row["priority"])
                if not 1 <= row["priority"] <= 5:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"CSV line {line}: priority must be an integer from 1 to 5")
            words.append(row)
    if not words:
        raise ValueError("CSV contains no words")
    return words


def select_words(words, priority=None, max_priority=None):
    return [word for word in words
            if (priority is None or word["priority"] == priority)
            and (max_priority is None or word["priority"] <= max_priority)]


async def speech(text, voice, rate, cache):
    import edge_tts
    key = hashlib.sha256(json.dumps([text, voice, rate], ensure_ascii=False).encode()).hexdigest()
    path = cache / (key + ".mp3")
    if path.exists() and path.stat().st_size:
        return path
    cache.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        # Separate temporary files also make interrupted downloads safe to retry.
        with tempfile.NamedTemporaryFile(dir=cache, suffix=".mp3", delete=False) as temp:
            pending = Path(temp.name)
        try:
            await edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", connect_timeout=15,
                                       receive_timeout=45).save(str(pending))
            if not pending.stat().st_size:
                raise RuntimeError("Speech service returned an empty recording")
            pending.replace(path)
            return path
        except Exception as error:
            if attempt == 2:
                raise RuntimeError(f"Speech generation failed for {voice}: {error}") from error
            await asyncio.sleep(attempt + 1)
        finally:
            pending.unlink(missing_ok=True)


async def voice_samples(config, output, cache, rate):
    import edge_tts
    try:
        available = await asyncio.wait_for(edge_tts.list_voices(), timeout=30)
    except Exception as error:
        raise RuntimeError(f"Cannot fetch voices from the speech service: {error or type(error).__name__}") from error
    voices = sorted((voice for voice in available
                     if voice["Locale"].split("-")[0].lower() == config["language"].lower()),
                    key=lambda voice: voice["ShortName"])
    if not voices:
        raise ValueError(f"No voices available for language {config['language']!r}")
    folder = output / "voices" / config["language"]
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"text": config["sample_text"], "rate": rate, "voices": []}
    failures = []
    for voice in voices:
        name = voice["ShortName"]
        destination = folder / (name + ".mp3")
        print(f"Voice sample: {name}", flush=True)
        try:
            source = await speech(config["sample_text"], name, rate, cache)
            destination.write_bytes(source.read_bytes())
            manifest["voices"].append({"name": name, "locale": voice["Locale"],
                                       "gender": voice["Gender"], "file": destination.name})
        except Exception as error:
            failures.append(f"{name}: {error}")
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    items = "\n".join(f'<p>{html.escape(v["name"])} ({html.escape(v["gender"])})<br>'
                      f'<audio controls preload="none" src="{v["file"]}"></audio></p>' for v in manifest["voices"])
    (folder / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Voice comparison</title>'
        '<h1>Voice comparison</h1><p>' + html.escape(config["sample_text"]) + '</p>' + items, encoding="utf-8")
    marker = folder / ".complete"
    marker.unlink(missing_ok=True)
    if failures:
        raise RuntimeError("Some voice samples failed; rerun to retry:\n" + "\n".join(failures))
    marker.write_text("complete\n", encoding="utf-8")
    print(f"Compare voices: {folder / 'index.html'}")


def assemble(segments, destination):
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        wav_path = Path(directory) / "practice.wav"
        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            for segment in segments:
                if isinstance(segment, (int, float)):
                    wav.writeframes(b"\x00\x00" * round(segment * 24000))
                else:
                    decoded = subprocess.run([ffmpeg, "-v", "error", "-i", str(segment),
                        "-f", "s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
                        check=True, capture_output=True)
                    wav.writeframes(decoded.stdout)
        pending = Path(directory) / "practice.mp3"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(wav_path),
                        "-codec:a", "libmp3lame", "-b:a", "96k", str(pending)],
                       check=True, capture_output=True)
        destination.write_bytes(pending.read_bytes())


async def run(args):
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not config.get("language", "").isalpha() or len(config["language"]) not in (2, 3):
        raise ValueError("Config language must be a two or three letter language code")
    for key in ("rate", "english_rate", "between_languages", "between_words", "repetitions"):
        value = getattr(args, key, None)
        if value is not None:
            config[key] = value
    for key in ("rate", "english_rate"):
        if type(config[key]) is not int or not -90 <= config[key] <= 100:
            raise ValueError(f"{key} must be an integer from -90 to 100")
    for key in ("between_languages", "between_words"):
        if not math.isfinite(config[key]) or not 0 <= config[key] <= 60:
            raise ValueError(f"{key} must be between 0 and 60 seconds")
    if type(config["repetitions"]) is not int or not 1 <= config["repetitions"] <= 20:
        raise ValueError("repetitions must be an integer from 1 to 20")
    if args.command == "samples":
        await voice_samples(config, args.output_dir, args.cache_dir, config["rate"])
        return
    words = select_words(read_words(args.csv or config_path.parent / config["csv"]),
                         args.priority, args.max_priority)
    if not words:
        raise ValueError("No words match the selected priorities")
    marker = args.output_dir / "voices" / config["language"] / ".complete"
    if config["language"].lower() != "en" and not marker.exists():
        await voice_samples(config, args.output_dir, args.cache_dir, config["rate"])
    segments = []
    for index, word in enumerate(words, 1):
        print(f"{index}/{len(words)}: {word['target_language']}", flush=True)
        target = await speech(word["target_language"], args.voice or config["voice"], config["rate"], args.cache_dir)
        english = None
        if args.mode != "target-only":
            english = await speech(word["english"], args.english_voice or config["english_voice"],
                                   config["english_rate"], args.cache_dir)
        for _ in range(config["repetitions"]):
            if args.mode == "english-target":
                segments.extend([english, config["between_languages"], target])
            elif args.mode == "target-english":
                segments.extend([target, config["between_languages"], english])
            else:
                segments.append(target)
            segments.append(config["between_words"])
    assemble(segments, args.output)
    print(f"Saved {args.output} ({len(words)} entries)")


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    for command in ("samples", "generate"):
        sub = commands.add_parser(command)
        sub.add_argument("--config", type=Path, default=ROOT / "config/german.json")
        sub.add_argument("--output-dir", type=Path, default=ROOT / "output")
        sub.add_argument("--cache-dir", type=Path, default=ROOT / ".cache/speech")
        sub.add_argument("--rate", type=int, help="Target speed percentage change; use --rate=-25")
        if command == "generate":
            sub.add_argument("--csv", type=Path)
            filters = sub.add_mutually_exclusive_group()
            filters.add_argument("--priority", type=int, choices=range(1, 6))
            filters.add_argument("--max-priority", type=int, choices=range(1, 6))
            sub.add_argument("--mode", choices=["english-target", "target-only", "target-english"], default="english-target")
            sub.add_argument("--voice")
            sub.add_argument("--english-voice")
            sub.add_argument("--english-rate", type=int)
            sub.add_argument("--between-languages", type=float)
            sub.add_argument("--between-words", type=float)
            sub.add_argument("--repetitions", type=int)
            sub.add_argument("--output", type=Path, default=ROOT / "output/practice.mp3")
    return cli


if __name__ == "__main__":
    try:
        asyncio.run(run(parser().parse_args()))
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Error: {error}")
