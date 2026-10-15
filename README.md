# Travel language audio

An editable vocabulary CSV and a small Python CLI for making MP3 practice recordings.
The German list contains basic travel words and phrases. **1 is the highest priority; 5 is the lowest.**

## Setup

Requires Python 3.9 or newer. From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Speech uses [edge-tts](https://github.com/rany2/edge-tts), a free online service requiring no API key.
An internet connection is required for voice discovery and uncached speech. Text is sent to Microsoft's speech service.
FFmpeg is supplied by `imageio-ffmpeg`; a separate system installation is unnecessary.

## Compare voices

```sh
python practice.py samples
```

Open `output/voices/de/index.html` in your browser to listen to every currently available German voice,
including Germany, Austria, and Switzerland variants. Each reads the same German passage.
The adjacent `manifest.json` records names, locales, sample text, and speed.
Set `voice` in `config/german.json` to your favorite, or pass `--voice de-DE-KatjaNeural`.
Katja is the default; choosing a voice is optional.

The first `generate` command automatically creates the samples if they haven't been created for that language.
Run `samples` again to refresh the voice list or compare a different speed. Failed samples are reported;
rerunning reuses successful cached speech.

## Generate recordings

All words at priority 3 or more important (levels **1–3**), English then German:

```sh
python practice.py generate --max-priority 3 --output output/german-english-target.mp3
```

Only priority 1, German alone:

```sh
python practice.py generate --priority 1 --mode target-only --output output/german-priority-1.mp3
```

Customize speed, pauses in seconds, and how many times each entry repeats:

```sh
python practice.py generate --max-priority 3 --rate=-25 --english-rate=-10 \
  --between-languages 2 --between-words 4 --repetitions 2 \
  --output output/german-slow.mp3
```

`--rate=-25` means 25% slower than normal. Defaults: target −15%, English −5%,
1.5 seconds between languages, 3 seconds after each entry, one repetition.
In `target-only` mode only the pause after each entry applies. Each repetition repeats the whole pattern.
`--mode target-english` lets you recall the English meaning before hearing it.
With neither priority option, every entry is included. CSV order is preserved.
Each invocation creates one file and replaces an existing file at the chosen output path.

## Edit vocabulary and defaults

Edit `vocabulary/german.csv` with a text editor or spreadsheet, preserving UTF-8 and the headers:

| Column | Meaning |
| --- | --- |
| `target_language` | German text to speak (include articles or phrases as desired) |
| `pronunciation` | English-friendly reading aid; never spoken |
| `english` | English meaning to speak |
| `priority` | Integer 1–5; 1 is most important |

Add/delete rows or change their priorities and rerun the command. Quote fields containing commas.
The reading aids are approximations: `kh` marks a German *ch* sound, and `ue` approximates *ü*
(say “ee” while rounding your lips). Listen to the samples for actual pronunciation.

Persistent speed/pause/voice defaults live in `config/german.json`; command flags override them.
Speech clips are cached under `.cache/speech/` using the text, voice, and speed, so vocabulary
and timing edits reuse unchanged clips. Recordings and caches are excluded from Git.

For another language, create a CSV with the same headers and copy the JSON config.
Change `language` to its base code (e.g. `fr`), `locale`, `voice`, `sample_text` to a passage in that language,
and `csv` to the CSV path relative to the config file. Use `--config config/french.json`
on either command. Every voice matching the base language gets a sample automatically on first generation.
The locale is descriptive; the selected voice determines the accent.

## Checks

```sh
python -m unittest discover -s tests -v
```

If the service is unavailable, generation reports an error; rerun later to reuse downloaded clips.
