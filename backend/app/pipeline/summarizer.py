# backend/app/pipeline/summarizer.py
import logging

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"


async def summarize_slice(client, messages: list[str]) -> str:
    """Generate a 1-2 sentence summary for a conversation slice."""
    text = "\n".join(messages)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
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
    return response.content[0].text.strip()


async def update_topic_summary(
    client,
    topic_name: str,
    current_summary: str | None,
    new_slice_summary: str,
) -> str:
    """Incrementally update a topic summary with a new slice."""
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

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def generate_topic_name(client, slice_summary: str) -> str:
    """Generate a short 3-5 word topic label in the language of the content."""
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=20,
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
    return response.content[0].text.strip()
