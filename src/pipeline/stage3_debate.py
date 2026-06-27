import json
import re
import logging
from src.models.llm_factory import get_llm_with_fallback

logger = logging.getLogger(__name__)

COMMITTEE_QUESTIONS = [
    "Which single assumption in your thesis has the highest uncertainty?",
    "What specific event or data point would cause you to completely reverse your position?",
    "Which risk is the market most underestimating right now for this stock?",
    "What catalyst could materially change the valuation within 6 months?",
    "Which financial metric deserves the greatest weight in the final rating, and why?"
]

class DebateOrchestrator:
    def __init__(self, config):
        self.config = config
        self.bull_llm = get_llm_with_fallback("bull_debate", config)
        self.bear_llm = get_llm_with_fallback("bear_debate", config)

    def run(self, audited_bundle: dict, ticker: str,
            company_name: str, duration: int, max_rounds: int = 8) -> dict:

        validated = audited_bundle.get("validated_reports", audited_bundle)

        bull_reports = {
            "fundamental": validated.get("fundamental"),
            "growth": validated.get("growth"),
            "moat": validated.get("moat"),
        }
        bear_reports = {
            "risk": validated.get("risk_narrative"),
            "macro": validated.get("macro"),
            "market_regime": validated.get("market_regime"),
        }

        context = {"ticker": ticker, "company_name": company_name, "duration": duration}
        transcript = []

        try:
            # Round 0 — independent opinions
            bull_r0 = self._call(self.bull_llm, "bull_round0", bull_reports, context)
            bear_r0 = self._call(self.bear_llm, "bear_round0", bear_reports, context)
            transcript.extend([
                {"round": 0, "role": "bull", "content": bull_r0},
                {"round": 0, "role": "bear", "content": bear_r0}
            ])

            if max_rounds <= 2:
                return self._finalize(transcript)

            # Round 1 — Bull opening
            bull_r1 = self._call(self.bull_llm, "bull_round1", bull_reports, context)
            transcript.append({"round": 1, "role": "bull", "content": bull_r1})

            # Round 2 — Bear challenge
            bear_r2 = self._call(self.bear_llm, "bear_round2", bear_reports, context, prior_round=bull_r1)
            transcript.append({"round": 2, "role": "bear", "content": bear_r2})

            if max_rounds <= 4:
                return self._finalize(transcript)

            # Round 3 — Bull rebuttal
            bull_r3 = self._call(self.bull_llm, "bull_round3", bull_reports, context, prior_round=bear_r2)
            transcript.append({"round": 3, "role": "bull", "content": bull_r3})

            # Round 4 — Bear rebuttal
            bear_r4 = self._call(self.bear_llm, "bear_round4", bear_reports, context, prior_round=bull_r3)
            transcript.append({"round": 4, "role": "bear", "content": bear_r4})

            if max_rounds <= 6:
                return self._finalize(transcript)

            # Round 5 — Committee Q&A
            qa_prompt = "Answer each of these 5 Investment Committee questions:\n" + \
                      "\n".join(f"{i+1}. {q}" for i, q in enumerate(COMMITTEE_QUESTIONS))
            bull_qa = self._call(self.bull_llm, "committee_qa", bull_reports, context, prior_round=qa_prompt)
            bear_qa = self._call(self.bear_llm, "committee_qa", bear_reports, context, prior_round=qa_prompt)
            transcript.extend([
                {"round": 5, "role": "bull_qa", "content": bull_qa},
                {"round": 5, "role": "bear_qa", "content": bear_qa}
            ])

            # Round 6 — Bull closing
            bull_r6 = self._call(self.bull_llm, "bull_closing", bull_reports, context,
                                 prior_round=json.dumps(transcript[-4:]))
            transcript.append({"round": 6, "role": "bull", "content": bull_r6})

            # Round 7 — Bear closing
            bear_r7 = self._call(self.bear_llm, "bear_closing", bear_reports, context,
                                 prior_round=json.dumps(transcript[-4:]))
            transcript.append({"round": 7, "role": "bear", "content": bear_r7})

            return self._finalize(transcript)

        except Exception as e:
            logger.error(f"Debate error: {e}")
            return self._finalize(transcript, error=str(e))

    def _call(self, llm, round_id, reports, context, prior_round=None) -> str:
        user_msg = f"Context: {json.dumps(context)}\n\nReports: {json.dumps(reports, default=str)}"
        if prior_round:
            user_msg += f"\n\nPrevious round:\n{prior_round}"

        instruction = self._load_round_instruction(round_id)
        return llm.complete(
            system_prompt=instruction,
            user_message=user_msg,
            response_format="text",
            temperature=0.5,
            max_tokens=2500
        )

    def _load_round_instruction(self, round_id: str) -> str:
        instructions = {
            "bull_round0": "You are a bullish fund manager. State your initial conviction score 0-10 and 2-sentence rationale BEFORE reading the bear's position.",
            "bear_round0": "You are a bearish short-seller. State your initial bear conviction score 0-10 (10 = extremely bearish) and 2-sentence rationale BEFORE reading the bull's position.",
            "bull_round1": "You are a bullish fund manager. Present your bull opening thesis with 5 data-backed arguments. Each argument must cite a specific number from the reports. End with: BULL CONVICTION SCORE: X/10",
            "bear_round2": "You are a bearish short-seller. Challenge the bull's opening. Cite specific numbers from the reports. Address at least 3 of the bull's arguments. End with: BEAR CONVICTION SCORE: X/10",
            "bull_round3": "You are a bullish fund manager. Rebuttal. Label each of your original points as CONCEDE or DEFEND with data. End with: BULL CONVICTION SCORE: X/10",
            "bear_round4": "You are a bearish short-seller. Final position. Update conviction score (max +/-1.5 from Round 0). End with: BEAR CONVICTION SCORE: X/10",
            "committee_qa": "Answer the 5 Investment Committee questions with specific data from the reports.",
            "bull_closing": "You are a bullish fund manager. Two-paragraph closing. Why did the bull case survive? What is the investor buying? End with: BULL CONVICTION SCORE: X/10",
            "bear_closing": "You are a bearish short-seller. Two-paragraph closing. What risk is the bull case glossing over? At what price would you become neutral? End with: BEAR CONVICTION SCORE: X/10",
        }
        return instructions.get(round_id, "Continue the debate.")

    def _extract_score(self, text: str, label: str) -> float:
        pattern = rf"{label}:\s*(\d+(?:\.\d+)?)/10"
        match = re.search(pattern, text, re.IGNORECASE)
        return float(match.group(1)) if match else 5.0

    def _finalize(self, transcript, error=None):
        bull_scores = []
        bear_scores = []
        for entry in transcript:
            if entry["role"] == "bull":
                s = self._extract_score(entry["content"], "BULL CONVICTION SCORE")
                bull_scores.append(s)
            elif entry["role"] == "bear":
                s = self._extract_score(entry["content"], "BEAR CONVICTION SCORE")
                bear_scores.append(s)

        bull_final = bull_scores[-1] if bull_scores else 5.0
        bear_final = bear_scores[-1] if bear_scores else 5.0

        return {
            "transcript": transcript,
            "bull_conviction": bull_final,
            "bear_conviction": bear_final,
            "high_uncertainty": abs(bull_final - bear_final) > 3.0,
            "error": error
        }
