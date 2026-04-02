# backend/app/pipeline/summarizer.py
import logging

from app.llm import create_text_message, extract_text_content, get_llm_model

logger = logging.getLogger(__name__)


def fallback_topic_name(text: str) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return "未命名话题"

    if any("\u4e00" <= char <= "\u9fff" for char in normalized):
        for sep in ("。", "！", "？", "\n"):
            normalized = normalized.replace(sep, " ")
        compact = normalized.replace("，", " ").replace("、", " ")
        return compact[:12].strip() or "未命名话题"

    words = normalized.split()
    return " ".join(words[:4]).strip() or "Untitled Topic"


async def summarize_slice(client, messages: list[str]) -> str:
    """Generate a 1-2 sentence summary for a conversation slice."""
    text = "\n".join(messages)
    llm_model = get_llm_model()
    response = await create_text_message(
        client,
        model=llm_model,
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": (
                    "Summarize this conversation in 1-2 sentences. "
                    "Be concise and factual. Focus on what was discussed.\n\n"
                    f"{text}"
                ),
            }
        ],
    )
    return extract_text_content(response) or fallback_topic_name(slice_summary)


async def update_topic_summary(
    client,
    topic_name: str,
    current_summary: str | None,
    new_slice_summary: str,
) -> str:
    """Incrementally update a topic summary with a new slice."""
    llm_model = get_llm_model()
    if current_summary:
        prompt = (
            f"Topic: {topic_name}\n\n"
            f"Current summary:\n{current_summary}\n\n"
            f"New discussion:\n{new_slice_summary}\n\n"
            "Update the topic summary to incorporate the new discussion. "
            "Keep it to 3-5 sentences. Be concise."
        )
    else:
        prompt = (
            f"Topic: {topic_name}\n\n"
            f"Discussion:\n{new_slice_summary}\n\n"
            "Write a 2-3 sentence summary of this topic."
        )

    response = await create_text_message(
        client,
        model=llm_model,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return extract_text_content(response)


async def generate_topic_name(client, slice_summary: str) -> str:
    """Generate a short 3-5 word topic label in the language of the content."""
    llm_model = get_llm_model()
    response = await create_text_message(
        client,
        model=llm_model,
        max_tokens=64,
        messages=[
            {
                "role": "user",
                "content": (
                    "Give this discussion a short topic label (3-5 words max). "
                    "Use the same language as the content. No punctuation.\n\n"
                    f"{slice_summary}"
                ),
            }
        ],
    )
    return extract_text_content(response)
