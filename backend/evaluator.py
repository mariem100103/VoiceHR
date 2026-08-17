import json
import os
from typing import Any, Dict
from google import genai

GEMINI_PROMPT = """
You are an expert language assessor analyzing a spoken candidate interview transcript.
Assess the candidate across 5 weighted dimensions (0-100 scale):
1. Interaction & Comprehension (25%): Understanding questions, relevant answers.
2. Fluency & Coherence (25%): Speech flow, logical structuring, lack of excessive hesitation.
3. Grammar & Language Control (20%): Accuracy of tenses, sentence structures.
4. Vocabulary & Range (15%): Lexical range, appropriate word choice.
5. Pronunciation & Intelligibility (15%): Clarity and intonation.

Analyze the transcript provided below and return ONLY a single valid JSON object with this exact schema
(no markdown, no explanation, just the raw JSON):

{{
  "interaction_score": <integer 0-100>,
  "fluency_score": <integer 0-100>,
  "grammar_score": <integer 0-100>,
  "vocabulary_score": <integer 0-100>,
  "pronunciation_score": <integer 0-100>,
  "confidence": "Low" or "Medium" or "High",
  "strengths": ["strength 1", "strength 2"],
  "concerns": ["concern 1", "concern 2"],
  "evidence": [
    {{
      "timestamp": "MM:SS or N/A",
      "quote": "exact quote from transcript",
      "dimension": "dimension name",
      "note": "assessor note"
    }}
  ],
  "inconclusive": false
}}

Set inconclusive to true ONLY if the candidate spoke fewer than 3 sentences total.

Scoring rules:
- Score only the candidate's user messages, never the agent's messages.
- A one-word answer, refusal, repeated "no", "I don't know", or irrelevant answer demonstrates no usable competency evidence.
- Do not award points merely because the candidate participated or audio was recorded.
- Every score above 20 must be supported by specific candidate evidence. When evidence is weak, score conservatively.
- If the candidate gives fewer than 3 substantive answers (at least 4 words each), set inconclusive to true and use scores of 0.
- If most answers are refusals or non-answers, set inconclusive to true and use scores of 0.

Assessment Language: {language}

Transcript:
{transcript}
"""


def map_score_to_cefr(score: int) -> str:
    if score >= 85:
        return "C1"
    elif score >= 65:
        return "B2"
    elif score >= 50:
        return "B1"
    else:
        return "A2"


def evaluate_transcript(transcript: list, language: str) -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")

    formatted_lines = []
    for item in transcript:
        time_sec = item.get("time_in_call_secs", 0)
        role = item.get("role", "unknown")
        msg = item.get("message", "")
        formatted_lines.append(f"[{time_sec}s] {role}: {msg}")
    formatted_transcript = "\n".join(formatted_lines) if formatted_lines else "(No transcript recorded)"

    client = genai.Client(api_key=api_key)
    # Avoid str.format() here: the prompt contains a JSON example with braces.
    prompt = GEMINI_PROMPT.replace("{language}", language.upper()).replace(
        "{transcript}", formatted_transcript
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    content = response.text
    # Strip markdown code fences if present
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON from Gemini: {e}\nRaw output: {content[:500]}")

    # Compute overall weighted score
    weighted_score = round(
        data.get("interaction_score", 0) * 0.25 +
        data.get("fluency_score", 0) * 0.25 +
        data.get("grammar_score", 0) * 0.20 +
        data.get("vocabulary_score", 0) * 0.15 +
        data.get("pronunciation_score", 0) * 0.15
    )

    data["overall_score"] = weighted_score
    data["result"] = map_score_to_cefr(weighted_score) if not data.get("inconclusive", False) else "Inconclusive"

    return data
