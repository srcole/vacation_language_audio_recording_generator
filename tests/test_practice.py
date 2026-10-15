import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import practice


class PracticeTests(unittest.TestCase):
    def test_priority_one_is_highest(self):
        words = [{"priority": n} for n in [4, 1, 3, 2, 5]]
        self.assertEqual([w["priority"] for w in practice.select_words(words, max_priority=3)], [1, 3, 2])
        self.assertEqual(practice.select_words(words, priority=1), [{"priority": 1}])

    def test_starter_csv(self):
        words = practice.read_words(practice.ROOT / "vocabulary/german.csv")
        self.assertTrue(words)
        self.assertTrue(all(w["pronunciation"] for w in words))

    def test_invalid_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "words.csv"
            for content in ["foo,bar\na,b\n", "target_language,pronunciation,english,priority\nHallo,h,hello,0\n",
                            "target_language,pronunciation,english,priority\nHallo,h,hello,1,extra\n"]:
                path.write_text(content)
                with self.assertRaises(ValueError):
                    practice.read_words(path)

    def test_patterns_and_repetitions(self):
        for mode, expected in [("english-target", ["hello", 1.5, "Hallo", 3.0]),
                               ("target-english", ["Hallo", 1.5, "hello", 3.0]),
                               ("target-only", ["Hallo", 3.0])]:
            with tempfile.TemporaryDirectory() as folder:
                output = Path(folder)
                marker = output / "voices/de/.complete"
                marker.parent.mkdir(parents=True)
                marker.touch()
                args = practice.parser().parse_args(["generate", "--mode", mode,
                        "--output-dir", folder, "--repetitions", "2"])
                async def fake_speech(text, *args):
                    return text
                with patch.object(practice, "read_words", return_value=[{"target_language": "Hallo", "english": "hello", "priority": 1}]), \
                     patch.object(practice, "speech", side_effect=fake_speech), \
                     patch.object(practice, "assemble") as assemble:
                    asyncio.run(practice.run(args))
                    self.assertEqual(assemble.call_args.args[0], expected * 2)

    def test_new_language_creates_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            args = practice.parser().parse_args(["generate", "--output-dir", folder, "--mode", "target-only"])
            with patch.object(practice, "read_words", return_value=[{"target_language": "Hallo", "english": "hello", "priority": 1}]), \
                 patch.object(practice, "voice_samples", new_callable=AsyncMock) as samples, \
                 patch.object(practice, "speech", new_callable=AsyncMock, return_value=Path("clip.mp3")), \
                 patch.object(practice, "assemble"):
                asyncio.run(practice.run(args))
                samples.assert_awaited_once()

    def test_invalid_timing_rejected(self):
        for value in ["nan", "inf", "-1"]:
            args = practice.parser().parse_args(["generate", "--between-words", value])
            with self.assertRaises(ValueError):
                asyncio.run(practice.run(args))

    def test_samples_include_regional_voices_reading_identical_text(self):
        voices = [{"ShortName": name, "Locale": locale, "Gender": "Female"}
                  for name, locale in [("de-DE-Test", "de-DE"), ("de-AT-Test", "de-AT"),
                                       ("de-CH-Test", "de-CH"), ("en-US-Test", "en-US")]]
        config = {"language": "de", "sample_text": "Guten Tag!"}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            clip = output / "source.mp3"
            clip.write_bytes(b"test audio")
            with patch("edge_tts.list_voices", new_callable=AsyncMock, return_value=voices), \
                 patch.object(practice, "speech", new_callable=AsyncMock, return_value=clip) as speech:
                asyncio.run(practice.voice_samples(config, output, output / "cache", -15))
            self.assertEqual(speech.await_count, 3)
            self.assertTrue(all(call.args[0] == "Guten Tag!" for call in speech.await_args_list))
            manifest = json.loads((output / "voices/de/manifest.json").read_text())
            self.assertEqual(len(manifest["voices"]), 3)
            self.assertTrue((output / "voices/de/.complete").exists())


if __name__ == "__main__":
    unittest.main()
