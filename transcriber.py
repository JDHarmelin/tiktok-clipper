"""Transcribes video audio using faster-whisper with word-level timestamps."""
import logging
from pathlib import Path
from faster_whisper import WhisperModel
from config import WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE

logger = logging.getLogger(__name__)

# Load model once at module level (lazy singleton)
_model = None


def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    return _model


def transcribe_video(file_path: str, language: str = None) -> dict:
    """
    Transcribe a video file. Returns segments with timestamps and word-level data.
    """
    # Validate file exists before attempting transcription
    if not Path(file_path).exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    if Path(file_path).stat().st_size == 0:
        return {"success": False, "error": f"File is empty: {file_path}"}

    try:
        model = _get_model()
    except Exception as e:
        logger.error(f"Failed to load Whisper model: {e}")
        return {"success": False, "error": f"Failed to load transcription model: {e}"}

    try:
        segments, info = model.transcribe(
            file_path,
            beam_size=5,
            word_timestamps=True,
            language=language,
            vad_filter=True,
        )

        result_segments = []
        all_words = []

        for segment in segments:
            seg_data = {
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text.strip(),
            }

            if segment.words:
                seg_data["words"] = [
                    {
                        "word": w.word,
                        "start": round(w.start, 2),
                        "end": round(w.end, 2),
                    }
                    for w in segment.words
                ]
                all_words.extend(seg_data["words"])

            result_segments.append(seg_data)

        formatted_transcript = "\n".join(
            f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}"
            for s in result_segments
        )

        return {
            "success": True,
            "language": info.language,
            "language_probability": round(info.language_probability, 2),
            "segments": result_segments,
            "words": all_words,
            "formatted_transcript": formatted_transcript,
            "total_duration": result_segments[-1]["end"] if result_segments else 0,
        }
    except Exception as e:
        logger.error(f"Transcription failed for {file_path}: {e}")
        return {"success": False, "error": f"Transcription failed: {e}"}
