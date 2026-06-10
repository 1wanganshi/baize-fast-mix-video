import math
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Union
from xml.sax.saxutils import unescape

from loguru import logger

from app.utils import utils

DEFAULT_VOXCPM_MODEL_NAME = "openbmb/VoxCPM2"
DEFAULT_VOXCPM_CFG_VALUE = 2.0
DEFAULT_VOXCPM_INFERENCE_TIMESTEPS = 10
DEFAULT_VOXCPM_SAMPLE_RATE = 48000
VOXCPM_VOICE_NAME = "voxcpm:clone"
NO_VOICE_NAME = "no-voice"
_NO_VOICE_ALIASES = {NO_VOICE_NAME, "none"}
_voxcpm_model_cache: dict[str, Any] = {}

VOXCPM_VOICE_PRESETS: dict[str, dict[str, str]] = {
    VOXCPM_VOICE_NAME: {
        "label": "上传参考音频克隆",
        "instruction": "",
    },
    "voxcpm:female_warm": {
        "label": "温柔女声",
        "instruction": "用年轻女性、温柔清晰、自然亲和的声音朗读。",
    },
    "voxcpm:female_bright": {
        "label": "清亮女声",
        "instruction": "用年轻女性、清亮活泼、语速自然的声音朗读。",
    },
    "voxcpm:male_calm": {
        "label": "沉稳男声",
        "instruction": "用成年男性、沉稳低缓、可靠有质感的声音朗读。",
    },
    "voxcpm:narrator": {
        "label": "纪录片旁白",
        "instruction": "用成熟中性的纪录片旁白声音朗读，节奏平稳，表达克制。",
    },
    "voxcpm:news": {
        "label": "新闻播报",
        "instruction": "用标准普通话新闻播报腔朗读，吐字清楚，节奏紧凑。",
    },
}


@dataclass
class SubMaker:
    subs: list[str] = field(default_factory=list)
    offset: list[tuple[int, int]] = field(default_factory=list)
    cues: list[Any] = field(default_factory=list)


def mktimestamp(time_unit: float) -> str:
    hour = math.floor(time_unit / 10**7 / 3600)
    minute = math.floor((time_unit / 10**7 / 60) % 60)
    seconds = (time_unit / 10**7) % 60
    return f"{hour:02d}:{minute:02d}:{seconds:06.3f}"


def get_voxcpm_voices() -> list[str]:
    return list(VOXCPM_VOICE_PRESETS.keys())


def get_voxcpm_voice_label(voice_name: str | None) -> str:
    preset = VOXCPM_VOICE_PRESETS.get(parse_voice_name(voice_name))
    if preset:
        return preset["label"]
    return str(voice_name or VOXCPM_VOICE_NAME)


def get_voxcpm_voice_instruction(voice_name: str | None) -> str:
    preset = VOXCPM_VOICE_PRESETS.get(parse_voice_name(voice_name))
    if not preset:
        return ""
    return preset.get("instruction", "").strip()


def parse_voice_name(name: str | None):
    return (name or "").replace("-Female", "").replace("-Male", "").strip()


def is_voxcpm_voice(voice_name: str | None):
    return parse_voice_name(voice_name).startswith("voxcpm:")


def is_no_voice(voice_name: str | None) -> bool:
    return str(voice_name or "").strip().lower() in _NO_VOICE_ALIASES


def estimate_no_voice_duration(text: str) -> float:
    normalized_text = (text or "").strip()
    if not normalized_text:
        return 3.0

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", normalized_text))
    ascii_words = len(re.findall(r"[A-Za-z0-9]+", normalized_text))
    other_chars = len(
        [
            ch
            for ch in normalized_text
            if not re.match(r"[\u4e00-\u9fffA-Za-z0-9\s]", ch)
            and unicodedata.category(ch)[0] in {"L", "N"}
        ]
    )
    sentence_count = max(len(utils.split_string_by_punctuations(normalized_text)), 1)
    duration = (
        cjk_chars / 4.2
        + ascii_words / 2.7
        + other_chars / 4.0
        + sentence_count * 0.25
    )
    return max(duration, 3.0)


def ensure_file_path_exists(file_path: str) -> None:
    dir_path = os.path.dirname(file_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


def generate_silent_audio(duration_seconds: float, output_file: str) -> bool:
    ensure_file_path_exists(output_file)
    ffmpeg_binary = utils.get_ffmpeg_binary()
    if not ffmpeg_binary:
        logger.error("ffmpeg binary is required to generate silent audio")
        return False

    if os.path.exists(output_file):
        os.remove(output_file)

    output_format = (utils.parse_extension(output_file) or "mp3").lower()
    codec_args = ["-c:a", "libmp3lame", "-q:a", "4"]
    if output_format == "wav":
        codec_args = ["-c:a", "pcm_s16le"]
    elif output_format not in {"mp3", "wav"}:
        codec_args = ["-c:a", "aac"]

    command = [
        ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t",
        f"{max(duration_seconds, 0.1):.3f}",
        *codec_args,
        output_file,
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        logger.error(
            "failed to generate silent audio: "
            f"{(result.stderr or result.stdout or '').strip()}"
        )
        return False
    if not os.path.exists(output_file) or os.path.getsize(output_file) <= 0:
        logger.error(f"silent audio output file is missing or empty: {output_file}")
        return False
    return True


def ensure_legacy_submaker_fields(sub_maker: SubMaker) -> SubMaker:
    if not hasattr(sub_maker, "subs"):
        sub_maker.subs = []
    if not hasattr(sub_maker, "offset"):
        sub_maker.offset = []
    if not hasattr(sub_maker, "cues"):
        sub_maker.cues = []
    return sub_maker


def populate_legacy_submaker_with_full_text(
    sub_maker: SubMaker, text: str, audio_duration_seconds: float
) -> SubMaker:
    sub_maker = ensure_legacy_submaker_fields(sub_maker)
    sub_maker.subs = []
    sub_maker.offset = []

    normalized_text = (text or "").strip()
    if not normalized_text:
        return sub_maker

    audio_duration_100ns = max(int(audio_duration_seconds * 10000000), 1)
    sentences = utils.split_string_by_punctuations(normalized_text) or [normalized_text]
    total_chars = sum(len(sentence.strip()) for sentence in sentences)
    if total_chars <= 0:
        sub_maker.subs.append(normalized_text)
        sub_maker.offset.append((0, audio_duration_100ns))
        return sub_maker

    current_offset = 0
    non_empty_sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    for index, sentence in enumerate(non_empty_sentences):
        if index == len(non_empty_sentences) - 1:
            sentence_end = audio_duration_100ns
        else:
            sentence_duration = max(
                int(audio_duration_100ns * (len(sentence) / total_chars)),
                1,
            )
            sentence_end = min(current_offset + sentence_duration, audio_duration_100ns)

        sub_maker.subs.append(sentence)
        sub_maker.offset.append((current_offset, sentence_end))
        current_offset = sentence_end

    return sub_maker


def _configure_pydub_ffmpeg(audio_segment_cls):
    configured_ffmpeg = utils.get_ffmpeg_binary()
    if configured_ffmpeg:
        audio_segment_cls.converter = configured_ffmpeg


def _get_audio_duration_seconds(audio_file: str) -> float:
    from moviepy.audio.io.AudioFileClip import AudioFileClip

    audio_clip = AudioFileClip(audio_file)
    try:
        return float(audio_clip.duration or 0)
    finally:
        audio_clip.close()


def _to_numpy_samples(samples):
    if hasattr(samples, "detach"):
        samples = samples.detach().cpu().numpy()
    return samples


def _extract_voxcpm_waveform(wav_data) -> tuple[int, Any]:
    sample_rate = DEFAULT_VOXCPM_SAMPLE_RATE
    samples = wav_data
    if isinstance(wav_data, tuple) and len(wav_data) == 2:
        sample_rate, samples = wav_data
    elif isinstance(wav_data, dict):
        sample_rate = wav_data.get("sample_rate") or wav_data.get("sampling_rate") or sample_rate
        samples = None
        for key in ("audio", "wav", "waveform"):
            if wav_data.get(key) is not None:
                samples = wav_data[key]
                break
    return int(sample_rate), _to_numpy_samples(samples)


def _write_voxcpm_waveform(voice_file: str, wav_data, sample_rate: int) -> float:
    import soundfile as sf
    from pydub import AudioSegment

    ensure_file_path_exists(voice_file)
    detected_sample_rate, samples = _extract_voxcpm_waveform(wav_data)
    sample_rate = int(sample_rate or detected_sample_rate or DEFAULT_VOXCPM_SAMPLE_RATE)
    if samples is None:
        raise ValueError("VoxCPM returned empty waveform data")

    output_format = (utils.parse_extension(voice_file) or "mp3").lower()
    if output_format == "wav":
        sf.write(voice_file, samples, sample_rate)
        return _get_audio_duration_seconds(voice_file)

    _configure_pydub_ffmpeg(AudioSegment)
    temp_wav_file = f"{os.path.splitext(voice_file)[0]}.voxcpm.tmp.wav"
    try:
        sf.write(temp_wav_file, samples, sample_rate)
        audio_segment = AudioSegment.from_wav(temp_wav_file)
        audio_segment.export(voice_file, format=output_format)
        return len(audio_segment) / 1000.0
    finally:
        if os.path.exists(temp_wav_file):
            try:
                os.remove(temp_wav_file)
            except OSError as exc:
                logger.warning(f"failed to remove temp VoxCPM wav: {str(exc)}")


def _load_voxcpm_model():
    try:
        from voxcpm import VoxCPM
    except ImportError as exc:
        raise RuntimeError(
            "VoxCPM is not installed in this Python environment. "
            "Install OpenBMB VoxCPM before using voice cloning."
        ) from exc

    if DEFAULT_VOXCPM_MODEL_NAME not in _voxcpm_model_cache:
        logger.info(f"loading VoxCPM model: {DEFAULT_VOXCPM_MODEL_NAME}")
        try:
            _voxcpm_model_cache[DEFAULT_VOXCPM_MODEL_NAME] = VoxCPM.from_pretrained(
                DEFAULT_VOXCPM_MODEL_NAME,
                load_denoiser=False,
            )
        except TypeError:
            _voxcpm_model_cache[DEFAULT_VOXCPM_MODEL_NAME] = VoxCPM.from_pretrained(
                DEFAULT_VOXCPM_MODEL_NAME
            )
    return _voxcpm_model_cache[DEFAULT_VOXCPM_MODEL_NAME]


def _get_voxcpm_sample_rate(model) -> int:
    tts_model = getattr(model, "tts_model", None)
    sample_rate = getattr(tts_model, "sample_rate", None) or getattr(
        model, "sample_rate", None
    )
    try:
        return int(sample_rate)
    except (TypeError, ValueError):
        return DEFAULT_VOXCPM_SAMPLE_RATE


def _apply_voxcpm_voice_instruction(text: str, voice_name: str | None) -> str:
    instruction = get_voxcpm_voice_instruction(voice_name)
    if not instruction:
        return text
    return f"({instruction}) {text}"


def _generate_voxcpm_waveform(
    model, text: str, reference_audio_file: str | None, voice_name: str | None = None
):
    kwargs = {
        "text": _apply_voxcpm_voice_instruction(text, voice_name),
        "cfg_value": DEFAULT_VOXCPM_CFG_VALUE,
        "inference_timesteps": DEFAULT_VOXCPM_INFERENCE_TIMESTEPS,
        "normalize": True,
        "denoise": True,
    }
    if reference_audio_file:
        kwargs["reference_wav_path"] = reference_audio_file

    try:
        return model.generate(**kwargs)
    except TypeError as exc:
        if reference_audio_file and "reference_wav_path" in str(exc):
            kwargs["prompt_wav_path"] = kwargs.pop("reference_wav_path")
            return model.generate(**kwargs)
        raise


def voxcpm_tts(
    text: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
    voice_name: str | None = VOXCPM_VOICE_NAME,
    reference_audio_file: str | None = None,
) -> Union[SubMaker, None]:
    text = (text or "").strip()
    if not text:
        logger.error("VoxCPM TTS text is empty")
        return None

    if reference_audio_file and not os.path.exists(reference_audio_file):
        logger.warning(f"VoxCPM reference audio not found: {reference_audio_file}")
        reference_audio_file = None

    for i in range(2):
        try:
            model = _load_voxcpm_model()
            wav_data = _generate_voxcpm_waveform(
                model=model,
                text=text,
                reference_audio_file=reference_audio_file,
                voice_name=voice_name,
            )
            audio_duration = _write_voxcpm_waveform(
                voice_file=voice_file,
                wav_data=wav_data,
                sample_rate=_get_voxcpm_sample_rate(model),
            )
            logger.success(f"VoxCPM tts succeeded: {voice_file}")
            sub_maker = ensure_legacy_submaker_fields(SubMaker())
            return populate_legacy_submaker_with_full_text(
                sub_maker=sub_maker,
                text=text,
                audio_duration_seconds=audio_duration,
            )
        except Exception as e:
            logger.error(f"VoxCPM TTS failed, try: {i + 1}, error: {str(e)}")

    return None


def tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
    reference_audio_file: str | None = None,
) -> Union[SubMaker, None]:
    if is_no_voice(voice_name):
        duration_seconds = estimate_no_voice_duration(text)
        if not generate_silent_audio(duration_seconds, voice_file):
            return None
        sub_maker = ensure_legacy_submaker_fields(SubMaker())
        return populate_legacy_submaker_with_full_text(
            sub_maker=sub_maker,
            text=text,
            audio_duration_seconds=duration_seconds,
        )

    if not is_voxcpm_voice(voice_name):
        logger.error(
            f"unsupported TTS voice '{voice_name}'. This desktop build only enables VoxCPM."
        )
        return None

    return voxcpm_tts(
        text=text,
        voice_rate=voice_rate,
        voice_file=voice_file,
        voice_volume=voice_volume,
        voice_name=voice_name,
        reference_audio_file=reference_audio_file,
    )


def _format_text(text: str) -> str:
    text = text.replace("[", " ")
    text = text.replace("]", " ")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("{", " ")
    text = text.replace("}", " ")
    return utils.normalize_script_for_subtitle_matching(text)


def _build_subtitle_formatter():
    def formatter(idx: int, start_time: float, end_time: float, sub_text: str) -> str:
        start_t = mktimestamp(start_time).replace(".", ",")
        end_t = mktimestamp(end_time).replace(".", ",")
        return f"{idx}\n{start_t} --> {end_t}\n{sub_text}\n"

    return formatter


_ARABIC_DIACRITICS = re.compile("[\u0610-\u061A\u064B-\u065F\u0670\u0640\u06D6-\u06ED]")


def _normalize_arabic(text: str) -> str:
    text = _ARABIC_DIACRITICS.sub("", text)
    for src, dst in (
        ("أإآٱ", "ا"),
        ("ىئ", "ي"),
        ("ة", "ه"),
        ("ؤ", "و"),
    ):
        for ch in src:
            text = text.replace(ch, dst)
    return text


def _match_script_line(script_lines: list[str], current_text: str, sub_index: int) -> str:
    if len(script_lines) <= sub_index:
        return ""

    target_line = script_lines[sub_index]
    if current_text == target_line:
        return target_line.strip()

    current_text_normalized = re.sub(r"[_\W]+", "", current_text)
    target_line_normalized = re.sub(r"[_\W]+", "", target_line)
    if current_text_normalized == target_line_normalized:
        return target_line.strip()

    current_ar = re.sub(r"[_\W]+", "", _normalize_arabic(current_text))
    target_ar = re.sub(r"[_\W]+", "", _normalize_arabic(target_line))
    if current_ar and current_ar == target_ar:
        return target_line.strip()

    return ""


def _write_subtitle_items(sub_items: list[str], subtitle_file: str) -> bool:
    from moviepy.video.tools import subtitles

    try:
        ensure_file_path_exists(subtitle_file)
        with open(subtitle_file, "w", encoding="utf-8") as file:
            file.write("\n".join(sub_items) + "\n")

        sbs = subtitles.file_to_subtitles(subtitle_file, encoding="utf-8")
        duration = max([tb for ((ta, tb), txt) in sbs]) if sbs else 0
        logger.info(
            f"completed, subtitle file created: {subtitle_file}, duration: {duration}"
        )
        return True
    except Exception as e:
        logger.error(f"failed, error: {str(e)}")
        if os.path.exists(subtitle_file):
            os.remove(subtitle_file)
        return False


def _build_subtitle_items_from_edge_cues(
    sub_maker: SubMaker, script_lines: list[str]
) -> list[str]:
    formatter = _build_subtitle_formatter()
    sub_items = []
    sub_index = 0
    current_text = ""
    current_start_time = None

    for cue in sub_maker.cues:
        cue_text = unescape(cue.content)
        if current_start_time is None:
            current_start_time = int(cue.start.total_seconds() * 10000000)

        current_end_time = int(cue.end.total_seconds() * 10000000)
        current_text += cue_text

        matched_text = _match_script_line(script_lines, current_text, sub_index)
        if not matched_text:
            continue

        sub_index += 1
        sub_items.append(
            formatter(
                idx=sub_index,
                start_time=current_start_time,
                end_time=current_end_time,
                sub_text=matched_text,
            )
        )
        current_text = ""
        current_start_time = None

    if current_text.strip():
        logger.warning(
            f"edge cues still have unmatched text after aggregation: {current_text}"
        )

    return sub_items


def _build_subtitle_items_from_legacy_submaker(
    sub_maker: SubMaker, script_lines: list[str]
) -> list[str]:
    formatter = _build_subtitle_formatter()
    start_time = -1.0
    sub_items = []
    sub_index = 0
    sub_line = ""

    legacy_offsets = getattr(sub_maker, "offset", [])
    legacy_subs = getattr(sub_maker, "subs", [])
    for item_index, (current_start_time, current_end_time) in enumerate(legacy_offsets):
        sub = legacy_subs[item_index] if item_index < len(legacy_subs) else ""
        if start_time < 0:
            start_time = current_start_time

        sub_line += unescape(sub)
        matched_text = _match_script_line(script_lines, sub_line, sub_index)
        if not matched_text:
            continue

        sub_index += 1
        sub_items.append(
            formatter(
                idx=sub_index,
                start_time=start_time,
                end_time=current_end_time,
                sub_text=matched_text,
            )
        )
        start_time = -1.0
        sub_line = ""

    if sub_line.strip():
        logger.warning(
            f"legacy subtitle items still have unmatched text after aggregation: {sub_line}"
        )

    return sub_items


def create_subtitle(sub_maker: SubMaker, text: str, subtitle_file: str):
    text = _format_text(text)
    script_lines = utils.split_string_by_punctuations(text)
    try:
        if hasattr(sub_maker, "cues") and sub_maker.cues:
            sub_items = _build_subtitle_items_from_edge_cues(sub_maker, script_lines)
        else:
            sub_items = _build_subtitle_items_from_legacy_submaker(
                sub_maker, script_lines
            )

        if len(sub_items) != len(script_lines):
            logger.warning(
                f"failed, sub_items len: {len(sub_items)}, script_lines len: {len(script_lines)}"
            )
            return

        _write_subtitle_items(sub_items, subtitle_file)
    except Exception as e:
        logger.error(f"failed, error: {str(e)}")


def _get_audio_duration_from_submaker(sub_maker: SubMaker):
    if hasattr(sub_maker, "cues") and sub_maker.cues:
        return sub_maker.cues[-1].end.total_seconds()

    legacy_offsets = getattr(sub_maker, "offset", [])
    if not legacy_offsets:
        return 0.0
    return legacy_offsets[-1][1] / 10000000


def _get_audio_duration_from_file(audio_file: str) -> float:
    if not os.path.exists(audio_file):
        logger.error(f"audio file does not exist: {audio_file}")
        return 0.0

    try:
        return _get_audio_duration_seconds(audio_file)
    except Exception as e:
        logger.error(f"failed to get audio duration from file: {str(e)}")
        return 0.0


def get_audio_duration(target: Union[str, SubMaker]) -> float:
    if isinstance(target, SubMaker):
        return _get_audio_duration_from_submaker(target)
    if isinstance(target, str):
        return _get_audio_duration_from_file(target)

    logger.error(f"Invalid target type: {type(target)}")
    return 0.0
