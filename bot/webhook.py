import logging
import httpx # Use httpx for async requests
from datetime import datetime
from typing import List, Dict, Any
from .config import Config

logger = logging.getLogger(__name__)

# Configure httpx client
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

async def send_webhook(config: Config, payload_data: List[Dict[str, Any]]) -> bool:
    """Sends the given list of message data as JSON to the configured webhook URL."""
    if not config.webhook_url:
        # This function shouldn't be called if URL isn't set, but double-check
        logger.warning("send_webhook called but WEBHOOK_URL not configured.")
        return False

    # Structure the final payload
    payload = {
        "bot_name": config.bot_name,
        "timestamp_utc": datetime.utcnow().isoformat(),
        "event_type": "periodic_message_batch",
        "messages": payload_data # The list of message dictionaries
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(config.webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Webhook batch sent successfully to {config.webhook_url}. Status: {response.status_code}")
            return True

    except httpx.TimeoutException:
        logger.error(f"Webhook request timed out for URL: {config.webhook_url}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Webhook request error for URL {config.webhook_url}: {e}", exc_info=True)
        return False
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Webhook request failed with status {e.response.status_code} for URL {config.webhook_url}. "
            f"Response: {e.response.text[:200]}..."
        )
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending webhook batch to {config.webhook_url}: {e}", exc_info=True)
        return False