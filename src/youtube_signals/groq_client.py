from __future__ import annotations
import json


class GroqClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required for transcript translation and extraction.")
        try:
            from groq import Groq
        except ImportError as exc:
            raise RuntimeError("groq is not installed. Run pip install -r requirements.txt.") from exc
        self.client = Groq(api_key=api_key)

    def json_chat(self, model: str, system: str, user: str, temperature: float = 0.1) -> object:
        response = self.client.chat.completions.create(model=model, temperature=temperature, response_format={"type": "json_object"}, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return json.loads(response.choices[0].message.content)

    def translate_audio(self, audio_path: str, model: str) -> str:
        with open(audio_path, "rb") as audio:
            response = self.client.audio.translations.create(file=(audio_path, audio.read()), model=model, response_format="json", temperature=0.0, prompt="Financial terms may include NSE company names, ticker symbols, rupee prices, targets, and stop losses.")
        return response.text

    def translate_text(self, text: str, model: str) -> str:
        data = self.json_chat(
            model,
            "Translate this finance-video caption text to English. Preserve company names, ticker symbols, and every number exactly. Return JSON object {\"text\": \"...\"} only.",
            text,
            0.0,
        )
        return str(data["text"])
