import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from .config import Config

# Use the same OpenAI client setup as the summarizer
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Database schema context for the AI
DB_SCHEMA_CONTEXT = """
Database Schema:
- chats(chat_id INTEGER PK, type TEXT, title TEXT, username TEXT UNIQUE, first_seen TIMESTAMP)
- users(user_id INTEGER PK, username TEXT UNIQUE, first_name TEXT, last_name TEXT, is_bot INTEGER, first_seen TIMESTAMP)
- messages(message_id INTEGER, chat_id INTEGER FK chats, sender_id INTEGER FK users, timestamp TIMESTAMP, text TEXT, entities TEXT JSON, media_type TEXT, media_info TEXT JSON, forwarded_to_user INTEGER)

Key Fields for Filtering:
- Chat: Use chat_id, title, or username from chats table.
- Date: Use timestamp from messages table (UTC).
- Sender: Use user_id or username from users table via sender_id in messages.
- Content: Use text, media_type ('photo', 'video', 'document', 'sticker', 'webpage'), or entities (JSON containing links like type='url' or 'text_link') from messages.
"""

SUPPORTED_FILTERS = {
    "chat_filter": "string (name/username) or integer (ID)",
    "date_filter": "string ('today', 'yesterday', 'YYYY-MM-DD')",
    "content_filter": "string ('links', 'photos', 'videos', 'documents', 'text:<keyword>')",
    "sender_filter": "string (username) or integer (ID)",
    "limit": "integer (max number of results, default 25)"
}

async def get_ai_client(config: Config, use_openrouter: bool = False) -> Optional[AsyncOpenAI]:
    """Helper to get configured AsyncOpenAI client for primary AI or OpenRouter."""
    api_key = None
    base_url = None
    client_name = "Primary AI"

    if use_openrouter:
        client_name = "OpenRouter"
        api_key = config.openrouter_api_key
        base_url = "https://openrouter.ai/api/v1" # Standard OpenRouter endpoint
        if not api_key:
            logger.error("OpenRouter API Key (OPENROUTER_API_KEY) not configured.")
            return None
    else:
        api_key = config.ai_api_key
        base_url = config.ai_api_base
        if not base_url or not api_key:
            logger.error("Primary AI API Base (AI_API_BASE) or Key (AI_API_KEY) not configured.")
            return None

    try:
        logger.debug(f"Initializing {client_name} client with base_url: {base_url}")
        # Add custom headers for OpenRouter if needed (e.g., referral)
        headers = None
        if use_openrouter:
            headers = {
                "HTTP-Referer": "YOUR_SITE_URL", # Optional: Replace with your site URL
                "X-Title": "AssetmaticMicro1", # Optional: Replace with your project title
            }

        return AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            default_headers=headers # Pass headers if defined
        )
    except Exception as e:
        logger.error(f"Failed to initialize {client_name} client: {e}")
        return None

async def get_ai_summary(config: Config, messages: List[Dict[str, Any]]) -> str:
    """Generates an AI summary for the given list of messages, with OpenRouter fallback."""
    if not messages:
        return "No new messages to summarize."

    # Prepare context (same for both primary and fallback)
    prompt_context = "Summarize the key points from the following messages. Be concise.\n\n"
    for msg in messages:
        sender = msg.get('sender_name', 'Unknown')
        chat = msg.get('chat_title', 'Unknown Chat')
        text = msg.get('text', '(no text)')
        media = f" [Media: {msg.get('media_type')}]" if msg.get('media_type') else ""
        timestamp = msg.get('timestamp', 'Unknown Time')
        ts_str = timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)
        prompt_context += f"- [{ts_str}] In '{chat}' by {sender}: {text}{media}\n"

    async def attempt_summary(use_openrouter: bool = False):
        client = await get_ai_client(config, use_openrouter=use_openrouter)
        if not client:
            provider_name = "OpenRouter" if use_openrouter else "Primary AI"
            return None, f"Error: {provider_name} client failed to initialize or is not configured."

        model_name = config.openrouter_fallback_model if use_openrouter else config.ai_model_name
        provider_name = "OpenRouter" if use_openrouter else "Primary AI"
        logger.info(f"Attempting summary with {provider_name} using model: {model_name}")
        try:
            chat_completion = await client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that summarizes message history concisely.",
                    },
                    {
                        "role": "user",
                        "content": prompt_context,
                    },
                ],
                model=model_name,
                max_tokens=500,
                temperature=0.5,
            )

            logger.debug(f"Raw {provider_name} completion object: {chat_completion}")

            if not chat_completion or not chat_completion.choices:
                logger.warning(f"{provider_name} completion has no choices. Response: {chat_completion}")
                return None, f"Error: {provider_name} returned no choices (likely content filtering or API issue)."
            if not chat_completion.choices[0].message:
                logger.warning(f"{provider_name} choice has no message attribute. Choice: {chat_completion.choices[0]}")
                return None, f"Error: {provider_name} response structure invalid (missing message)."

            summary = chat_completion.choices[0].message.content
            if summary is None:
                logger.warning(f"{provider_name} message content is None. Message object: {chat_completion.choices[0].message}")
                return None, f"Error: {provider_name} returned an empty summary message."

            logger.info(f"{provider_name} summary received successfully.")
            return summary.strip(), None # Success
        except Exception as e:
            logger.error(f"Error calling {provider_name} for summary: {e}", exc_info=True)
            return None, f"Error: Failed to generate summary with {provider_name} - {e}" # Failure with reason

    # --- Try Primary First ---
    summary, error = await attempt_summary(use_openrouter=False)
    if summary is not None:
        return summary

    logger.warning(f"Primary AI summary failed: {error}. Attempting fallback with OpenRouter...")

    # --- Try Fallback (OpenRouter) ---
    if config.openrouter_api_key: # Only attempt if key is configured
        summary_fallback, error_fallback = await attempt_summary(use_openrouter=True)
        if summary_fallback is not None:
            return summary_fallback
        else:
            logger.error(f"OpenRouter fallback summary also failed: {error_fallback}")
            # Return the fallback error if it exists, otherwise the primary error
            return error_fallback or error
    else:
        logger.warning("OpenRouter API key not configured. Cannot attempt fallback.")
        return error # Return the original error from primary AI

async def extract_query_params_from_nlp(config: Config, nlp_query: str) -> Optional[Dict[str, Any]]:
    """Uses AI to extract structured query parameters, with OpenRouter fallback."""
    system_prompt = f"""You are an AI assistant that converts natural language queries about saved Telegram messages into structured JSON filters.

Here is the database context:
{DB_SCHEMA_CONTEXT}

Here are the valid filter keys and their expected value types:
{json.dumps(SUPPORTED_FILTERS, indent=2)}

Convert the user's query into a JSON object containing ONLY the relevant filter keys based on the query.
- Use 'today', 'yesterday', or 'YYYY-MM-DD' format for dates.
- For content like links, use 'links'. For photos, use 'photos'. For specific text, use 'text:<keyword>'.
- If a filter type is not mentioned, omit the key.
- Do not add keys that are not in the supported list.
- If the query is unclear or cannot be mapped to the filters, return an empty JSON object {{}}.
- Your response MUST be ONLY the JSON object, with no other text before or after it.
"""

    async def attempt_extraction(use_openrouter: bool = False):
        client = await get_ai_client(config, use_openrouter=use_openrouter)
        if not client:
            provider_name = "OpenRouter" if use_openrouter else "Primary AI"
            return None, f"Error: {provider_name} client failed to initialize or is not configured."

        model_name = config.openrouter_fallback_model if use_openrouter else config.ai_model_name
        provider_name = "OpenRouter" if use_openrouter else "Primary AI"
        logger.info(f"Attempting param extraction with {provider_name} using model: {model_name}. Query: '{nlp_query}'")
        try:
            chat_completion = await client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": nlp_query,
                    },
                ],
                model=model_name,
                temperature=0.1,
                max_tokens=200
            )
            logger.debug(f"Raw {provider_name} completion object for extraction: {chat_completion}")

            if not chat_completion or not chat_completion.choices:
                logger.warning(f"{provider_name} extraction has no choices. Response: {chat_completion}")
                return None, f"Error: {provider_name} returned no choices for extraction." # Indicate failure
            if not chat_completion.choices[0].message:
                logger.warning(f"{provider_name} extraction choice has no message. Choice: {chat_completion.choices[0]}")
                return None, f"Error: {provider_name} extraction response invalid."

            response_content = chat_completion.choices[0].message.content
            if response_content is None:
                logger.warning(f"{provider_name} extraction content is None. Message: {chat_completion.choices[0].message}")
                return None, f"Error: {provider_name} returned empty content for extraction."

            try:
                extracted_params = json.loads(response_content)
                validated_params = {k: v for k, v in extracted_params.items() if k in SUPPORTED_FILTERS}
                logger.info(f"{provider_name} successfully extracted and validated parameters: {validated_params}")
                return validated_params, None # Success
            except json.JSONDecodeError:
                logger.error(f"{provider_name} did not return valid JSON for extraction: {response_content}")
                return None, f"Error: {provider_name} returned invalid JSON." # Failure
            except Exception as e:
                logger.error(f"Error processing {provider_name} JSON response: {e}", exc_info=True)
                return None, f"Error: Could not process JSON from {provider_name}." # Failure
        except Exception as e:
            logger.error(f"Error calling {provider_name} for extraction: {e}", exc_info=True)
            return None, f"Error: Failed call to {provider_name} for extraction - {e}" # Failure

    # --- Try Primary First ---
    params, error = await attempt_extraction(use_openrouter=False)
    if params is not None: # Success or empty dict (understood but no params) mean proceed
        return params

    logger.warning(f"Primary AI param extraction failed: {error}. Attempting fallback with OpenRouter...")

    # --- Try Fallback (OpenRouter) ---
    if config.openrouter_api_key: # Only attempt if key is configured
        params_fallback, error_fallback = await attempt_extraction(use_openrouter=True)
        if params_fallback is not None: # Success or empty dict
            return params_fallback
        else:
            logger.error(f"OpenRouter fallback extraction also failed: {error_fallback}")
            # Let the caller handle the ultimate failure (e.g., reply to user)
            return None # Indicate total failure
    else:
        logger.warning("OpenRouter API key not configured. Cannot attempt fallback for extraction.")
        return None # Indicate total failure