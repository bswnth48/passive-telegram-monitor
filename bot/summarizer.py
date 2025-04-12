import logging
from openai import AsyncOpenAI
from typing import List, Dict, Any # Added Dict, Any
from .config import Config

logger = logging.getLogger(__name__)

def format_message_for_prompt(msg: Dict[str, Any]) -> str:
    """Formats a single message dictionary into a string for the AI prompt."""
    ts = msg.get('timestamp', '?')
    sender = msg.get('sender_name', 'Unknown')
    is_bot = msg.get('sender_is_bot', False)
    chat = msg.get('chat_title', 'Unknown Chat')
    text = msg.get('text', '')
    media = msg.get('media_type')
    entities = msg.get('entities')

    sender_str = f"{sender}{' [Bot]' if is_bot else ''}"
    media_str = f" [Media: {media}]" if media else ""
    link_str = " [Links]" if entities and any(e.get('type') in ['url', 'text_link'] for e in entities) else ""

    # Combine, ensuring text is present or placeholder
    content = text if text else f"(No text content - {media_str.strip()})"

    return f"{ts} [{chat}] {sender_str}:{media_str}{link_str} {content}"

async def get_ai_summary(config: Config, messages: List[Dict[str, Any]]) -> str | None:
    """Generates a summary of provided message dictionaries using an OpenAI-compatible API."""
    if not config.ai_api_key or not config.ai_api_base:
        logger.warning("AI API key or base URL not configured. Cannot generate summary.")
        return "AI summarization not configured."

    if not messages:
        return "No new messages found to summarize."

    # Format messages for the prompt
    formatted_messages = [format_message_for_prompt(msg) for msg in messages]

    prompt_header = f"Summarize the key points, topics, and any urgent items from the following {len(messages)} Telegram messages observed recently:\n\n---"
    prompt_body = "\n".join(formatted_messages)
    full_prompt = prompt_header + "\n" + prompt_body

    # Limit prompt length (Example: ~15k tokens might be 60k chars)
    # Be generous as summarization usually handles long context well
    MAX_CHARS = 60000
    if len(full_prompt) > MAX_CHARS:
        logger.warning(f"Prompt length ({len(full_prompt)} chars) exceeds limit ({MAX_CHARS}). Truncating.")
        # Truncate the body, keeping the header
        chars_to_remove = len(full_prompt) - MAX_CHARS
        truncated_body = prompt_body[:-chars_to_remove]
        full_prompt = prompt_header + "\n... (truncated)...\n" + truncated_body

    try:
        client = AsyncOpenAI(
            api_key=config.ai_api_key,
            base_url=config.ai_api_base,
        )

        logger.info(f"Sending {len(messages)} messages ({len(full_prompt)} chars) to AI for summarization using model {config.ai_model_name}...")

        response = await client.chat.completions.create(
            model=config.ai_model_name,
            messages=[
                {"role": "system", "content": "You are a concise assistant summarizing Telegram chat logs. Focus on key topics, questions, links shared, and potential action items. Ignore pleasantries and routine messages unless significant."},
                {"role": "user", "content": full_prompt}
            ],
            temperature=0.6,
            # max_tokens=1000, # Optional: Limit response size
        )

        summary = response.choices[0].message.content.strip()
        logger.info("Successfully received summary from AI.")
        return summary

    except Exception as e:
        logger.error(f"Error calling AI API: {e}", exc_info=True)
        return f"Error generating summary: {e}"