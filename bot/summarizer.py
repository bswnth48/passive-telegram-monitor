import logging
from openai import AsyncOpenAI # Use async version
from .config import Config

logger = logging.getLogger(__name__)

async def get_ai_summary(config: Config, messages: list[str]) -> str | None:
    """Generates a summary of provided messages using an OpenAI-compatible API."""
    if not config.ai_api_key or not config.ai_api_base:
        logger.warning("AI API key or base URL not configured. Cannot generate summary.")
        return "AI summarization not configured."

    if not messages:
        return "No messages found today to summarize."

    # Combine messages into a single prompt
    # Add context/instruction for the AI
    prompt_header = "Summarize the key points, topics, and any urgent items from the following Telegram messages observed today:\n\n---\n"
    prompt_body = "\n".join(messages)
    full_prompt = prompt_header + prompt_body

    # Limit prompt length if necessary (check model limits)
    # simplified_prompt = full_prompt[:MAX_PROMPT_LENGTH] # Define MAX_PROMPT_LENGTH based on model

    try:
        client = AsyncOpenAI(
            api_key=config.ai_api_key,
            base_url=config.ai_api_base,
        )

        logger.info(f"Sending {len(messages)} messages to AI for summarization using model {config.ai_model_name}...")

        response = await client.chat.completions.create(
            model=config.ai_model_name,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that summarizes Telegram chat logs."},
                {"role": "user", "content": full_prompt}
            ],
            temperature=0.5, # Adjust for creativity vs factualness
            # max_tokens=500, # Limit response length if needed
        )

        summary = response.choices[0].message.content.strip()
        logger.info("Successfully received summary from AI.")
        return summary

    except Exception as e:
        logger.error(f"Error calling AI API: {e}", exc_info=True)
        return f"Error generating summary: {e}"