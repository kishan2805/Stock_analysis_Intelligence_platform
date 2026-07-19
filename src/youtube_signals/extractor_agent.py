from __future__ import annotations
from .cache import SignalCache
from .groq_client import GroqClient
from .schemas import StockCall, Transcript, VideoMeta

PROMPT_VERSION = "1"
SYSTEM = """Extract only explicit, tradeable Indian-stock calls from an English YouTube transcript. Return JSON object {\"calls\": [...]}. Each call needs company_name_raw and action (BUY, SELL, HOLD, WATCH, AVOID). Prices must be numbers stated in the transcript, otherwise null. Never infer. rationale_snippet is a <25-word paraphrase. Caption timestamps appear as [MM:SS]; copy the closest one as evidence_timestamp_seconds (convert to seconds). evidence_text is a <=20-word non-verbatim locator/paraphrase. Ignore indices, general market commentary and non-recommendations."""


class ExtractorAgent:
    def __init__(self, cache: SignalCache, groq: GroqClient, model: str, temperature: float):
        self.cache, self.groq, self.model, self.temperature = cache, groq, model, temperature

    def extract(self, video: VideoMeta, transcript: Transcript) -> list[StockCall]:
        key = self.cache.key("extraction-v" + PROMPT_VERSION, video.video_id)
        cached = self.cache.get(key)
        if cached is not None:
            return [StockCall.model_validate(x) for x in cached]
        data = self.groq.json_chat(self.model, SYSTEM, f"Title: {video.title}\nChannel: {video.channel_name}\nPublished: {video.publish_date}\nTranscript:\n{transcript.text_en}", self.temperature)
        calls = []
        for raw in data.get("calls", []):
            raw.update(video_id=video.video_id, channel_name=video.channel_name, publish_date=video.publish_date)
            calls.append(StockCall.model_validate(raw))
        self.cache.set(key, [call.model_dump(mode="json") for call in calls])
        return calls
