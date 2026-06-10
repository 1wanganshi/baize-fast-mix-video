import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import voice as vs


class _FakeVoxCPM:
    def __init__(self):
        self.tts_model = SimpleNamespace(sample_rate=48000)
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return [0.0, 0.0, 0.0]


class TestVoiceService(unittest.TestCase):
    def test_tts_only_accepts_voxcpm_or_no_voice(self):
        self.assertIsNone(
            vs.tts(
                text="legacy voice should fail",
                voice_name="zh-CN-XiaoxiaoNeural",
                voice_rate=1.0,
                voice_file="unused.mp3",
            )
        )

    def test_tts_dispatches_voxcpm(self):
        sentinel = object()
        with patch.object(vs, "voxcpm_tts", return_value=sentinel) as voxcpm_tts:
            result = vs.tts(
                text="hello",
                voice_name=vs.VOXCPM_VOICE_NAME,
                voice_rate=1.0,
                voice_file="voice.mp3",
                voice_volume=1.2,
                reference_audio_file="reference.wav",
            )

        self.assertIs(result, sentinel)
        voxcpm_tts.assert_called_once_with(
            text="hello",
            voice_rate=1.0,
            voice_file="voice.mp3",
            voice_volume=1.2,
            voice_name=vs.VOXCPM_VOICE_NAME,
            reference_audio_file="reference.wav",
        )

    def test_voxcpm_preset_adds_voice_instruction(self):
        fake_model = _FakeVoxCPM()
        vs._generate_voxcpm_waveform(
            model=fake_model,
            text="hello",
            reference_audio_file=None,
            voice_name="voxcpm:male_calm",
        )

        self.assertIn("成年男性", fake_model.generate_kwargs["text"])
        self.assertTrue(fake_model.generate_kwargs["text"].endswith("hello"))

    def test_voxcpm_uses_reference_wav_path_without_server_fallback(self):
        fake_model = _FakeVoxCPM()
        with tempfile.TemporaryDirectory() as tmp_dir:
            reference = Path(tmp_dir) / "reference.wav"
            reference.write_bytes(b"fake-wav")
            output = Path(tmp_dir) / "voice.mp3"

            with patch.object(vs, "_load_voxcpm_model", return_value=fake_model), patch.object(
                vs, "_write_voxcpm_waveform", return_value=2.5
            ) as write_waveform:
                sub_maker = vs.voxcpm_tts(
                    text="第一句。第二句。",
                    voice_rate=1.0,
                    voice_file=str(output),
                    reference_audio_file=str(reference),
                )

        self.assertIsNotNone(sub_maker)
        self.assertEqual(fake_model.generate_kwargs["reference_wav_path"], str(reference))
        self.assertNotIn("prompt_wav_path", fake_model.generate_kwargs)
        write_waveform.assert_called_once()
        self.assertGreater(vs.get_audio_duration(sub_maker), 0)

    def test_no_voice_tts_generates_silent_audio_and_timeline(self):
        def fake_run(command, **_kwargs):
            self.assertEqual(command[0], "/tmp/fake-ffmpeg")
            self.assertIn("anullsrc=channel_layout=stereo:sample_rate=44100", command)
            Path(command[-1]).write_bytes(b"fake-silent-mp3")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            vs.utils, "get_ffmpeg_binary", return_value="/tmp/fake-ffmpeg"
        ), patch.object(vs.subprocess, "run", side_effect=fake_run):
            voice_file = str(Path(tmp_dir) / "silent.mp3")
            sub_maker = vs.tts(
                text="第一句。Second sentence.",
                voice_name=vs.NO_VOICE_NAME,
                voice_rate=1.0,
                voice_file=voice_file,
            )

            self.assertEqual(Path(voice_file).read_bytes(), b"fake-silent-mp3")

        self.assertEqual(getattr(sub_maker, "subs", []), ["第一句", "Second sentence"])
        self.assertEqual(len(getattr(sub_maker, "offset", [])), 2)
        self.assertGreater(vs.get_audio_duration(sub_maker), 0)

    def test_create_subtitle_from_legacy_timeline(self):
        sub_maker = vs.populate_legacy_submaker_with_full_text(
            sub_maker=vs.SubMaker(),
            text="第一句。第二句。",
            audio_duration_seconds=4.0,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            vs.create_subtitle(sub_maker, "第一句。第二句。", str(subtitle_file))

            content = subtitle_file.read_text(encoding="utf-8")

        self.assertIn("00:00:00,000 -->", content)
        self.assertIn("第一句", content)
        self.assertIn("第二句", content)


if __name__ == "__main__":
    unittest.main()
