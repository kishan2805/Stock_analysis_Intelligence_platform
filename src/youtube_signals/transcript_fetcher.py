from __future__ import annotations
import subprocess
import tempfile
from pathlib import Path
from .cache import SignalCache
from .groq_client import GroqClient
from .schemas import Transcript, VideoMeta
from .media import get_ffmpeg_path


class TranscriptFetcher:
    def __init__(self, cache: SignalCache, groq: GroqClient, translation_model: str, caption_translation_model: str):
        self.cache, self.groq = cache, groq
        self.translation_model, self.caption_translation_model = translation_model, caption_translation_model

    def fetch(self, video: VideoMeta) -> Transcript:
        key = self.cache.key("transcript-v1", video.video_id)
        cached = self.cache.get(key)
        if cached:
            return Transcript.model_validate(cached)
        transcript = self._captions(video.video_id)
        if transcript is None:
            transcript = self._whisper(video.url, video.video_id)
        self.cache.set(key, transcript.model_dump(mode="json"))
        return transcript

    def _captions(self, video_id: str) -> Transcript | None:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
            fetched = api.fetch(video_id)
            # Keep source timestamps in the prompt. They are not shown as a quote,
            # but make the extracted level traceable in the original video.
            text = "\n".join(
                f"[{int(item.start // 60):02d}:{int(item.start % 60):02d}] {item.text}"
                for item in fetched
            )
            language = getattr(fetched, "language_code", "unknown")
            if language != "en":
                text = self.groq.translate_text(text, self.caption_translation_model)
            return Transcript(video_id=video_id, text_en=text, source="captions", original_language=language)
        except Exception:
            return None

    def _whisper(self, url: str, video_id: str) -> Transcript:
        with tempfile.TemporaryDirectory(prefix="yt-audio-") as temp_dir:
            output = str(Path(temp_dir) / "audio.%(ext)s")
            # Groq accepts YouTube's native m4a/webm audio formats. Avoiding a
            # transcode means captionless short videos also work without ffmpeg.
            command = ["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-o", output, url]
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise RuntimeError("No captions and audio download failed; video was skipped.")
            audio_files = list(Path(temp_dir).glob("audio.*"))
            if not audio_files:
                raise RuntimeError("No captions and audio download failed; video was skipped.")
            audio_paths = audio_files
            if audio_files[0].stat().st_size > 24 * 1024 * 1024:
                if not (ffmpeg := get_ffmpeg_path()):
                    raise RuntimeError("No captions and audio exceeds Groq's upload limit; install ffmpeg to enable automatic chunking.")
                chunk_pattern = str(Path(temp_dir) / "chunk-%03d.mp3")
                chunk = subprocess.run([ffmpeg, "-y", "-i", str(audio_files[0]), "-ar", "16000", "-ac", "1", "-b:a", "32k", "-f", "segment", "-segment_time", "1200", chunk_pattern], capture_output=True, text=True, timeout=300)
                if chunk.returncode:
                    raise RuntimeError("Could not chunk captionless audio for transcription; video was skipped.")
                audio_paths = sorted(Path(temp_dir).glob("chunk-*.mp3"))
            text = "\n".join(self.groq.translate_audio(str(path), self.translation_model) for path in audio_paths)
        return Transcript(video_id=video_id, text_en=text, source="whisper", original_language="unknown")
