import logging
import httpx # Use httpx for async requests
from datetime import datetime
from .config import Config

logger = logging.getLogger(__name__)

# Configure httpx client (can be customized further)
# Set timeouts to prevent hanging indefinitely
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

async def send_webhook(config: Config, payload: dict):
    """Sends the given payload as JSON to the configured webhook URL."""
    if not config.webhook_url:
        logger.warning("WEBHOOK_URL not configured. Skipping webhook send.")
        return False # Indicate failure/skip

    # Add standard info to the payload
    payload["bot_name"] = config.bot_name
    payload["timestamp_utc"] = datetime.utcnow().isoformat()

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(config.webhook_url, json=payload)

            # Raise exception for bad status codes (4xx or 5xx)
            response.raise_for_status()

            logger.info(f"Webhook sent successfully to {config.webhook_url}. Status: {response.status_code}")
            return True # Indicate success

    except httpx.TimeoutException:
        logger.error(f"Webhook request timed out for URL: {config.webhook_url}")
        return False
    except httpx.RequestError as e:
        # Includes connection errors, invalid URLs, etc.
        logger.error(f"Webhook request error for URL {config.webhook_url}: {e}", exc_info=True)
        return False
    except httpx.HTTPStatusError as e:
        # Handle specific HTTP errors (like 404, 500)
        logger.error(
            f"Webhook request failed with status {e.response.status_code} for URL {config.webhook_url}. "
            f"Response: {e.response.text[:200]}..." # Log part of the response
        )
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending webhook to {config.webhook_url}: {e}", exc_info=True)
        return False