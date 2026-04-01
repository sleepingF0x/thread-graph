# backend/app/pipeline/jargon.py
import json
import logging

from app.llm import get_llm_model

logger = logging.getLogger(__name__)
AUTO_CONFIRM_THRESHOLD = 0.8
MAX_INJECTED_TERMS = 50

EXTRACTION_PROMPT = """Analyze these chat messages and identify jargon, abbreviations, internal terms, slang, and coded language that would be non-obvious to an outsider.

Return ONLY valid JSON in this format:
{{"terms": [{{"word": "term", "meanings": [{{"meaning": "explanation", "confidence": 0.0-1.0}}], "context_examples": ["example sentence"]}}]}}

Rules:
- Only include terms that are non-obvious to outsiders
- confidence: 1.0 = certain, 0.5 = guessing
- If no jargon found, return {{"terms": []}}
- Do not include common words

Messages:
{messages}"""


async def extract_terms(
    client,
    messages: list[str],
    group_id: int,
) -> list[dict]:
    if not messages:
        return []

    text = "\n".join(messages[:100])
    llm_model = get_llm_model()
    response = await client.messages.create(
        model=llm_model,
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": EXTRACTION_PROMPT.format(messages=text),
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code blocks if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Jargon extractor returned invalid JSON: {raw[:200]}")
        return []

    results = []
    for term in data.get("terms", []):
        max_confidence = max(
            (m.get("confidence", 0) for m in term.get("meanings", [])),
            default=0,
        )
        results.append(
            {
                "word": term.get("word", ""),
                "meanings": term.get("meanings", []),
                "examples": term.get("context_examples", []),
                "needs_review": max_confidence < AUTO_CONFIRM_THRESHOLD,
                "group_id": group_id,
            }
        )
    return results


def build_system_context(confirmed_terms: list[dict]) -> str:
    if not confirmed_terms:
        return ""

    lines = ["Known terms in this group:"]
    for term in confirmed_terms[:MAX_INJECTED_TERMS]:
        meanings = term.get("meanings", [])
        if meanings:
            meaning_str = meanings[0].get("meaning", "")
            lines.append(f"- {term['word']}: {meaning_str}")

    return "\n".join(lines)
