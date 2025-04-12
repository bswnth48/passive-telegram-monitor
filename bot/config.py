import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

@dataclass
class Config:
    api_id: int
    api_hash: str
    bot_name: str
    webhook_interval_minutes: int
    telegram_groups: List[str]
    ai_api_base: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_model_name: str = "gemini-pro"
    webhook_url: Optional[str] = None

def load_config() -> Config:
    """Loads configuration from environment variables."""
    load_dotenv()
    logger.info("Loaded environment variables from .env file if present.")

    # Telegram settings
    api_id_str = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    bot_name = os.getenv("BOT_NAME", "DefaultBotName")
    webhook_interval_str = os.getenv("WEBHOOK_INTERVAL_MINUTES", "30")
    telegram_groups_str = os.getenv("TELEGRAM_GROUPS")
    webhook_url = os.getenv("WEBHOOK_URL")

    # AI Settings
    ai_api_base = os.getenv("AI_API_BASE")
    ai_api_key = os.getenv("AI_API_KEY")
    ai_model_name = os.getenv("AI_MODEL_NAME", "gemini-pro")

    # --- Validation (Telegram part remains mostly the same) ---
    missing_vars = []
    if not api_id_str: missing_vars.append("API_ID")
    if not api_hash: missing_vars.append("API_HASH")
    if not webhook_url: missing_vars.append("WEBHOOK_URL") # Still needed by config structure
    # Allow empty TELEGRAM_GROUPS
    if not telegram_groups_str:
         logger.warning("Environment variable TELEGRAM_GROUPS is not set. The bot will not join any groups.")
         telegram_groups = []
    else:
        telegram_groups = [group.strip() for group in telegram_groups_str.split(',') if group.strip()]

    # Check AI vars only if summarization might be used (optional for basic run)
    # If AI_API_KEY is missing, log a warning but allow running without summarizer
    if not ai_api_key:
        logger.warning("AI_API_KEY environment variable is not set. Summarization feature will be disabled.")
    if not ai_api_base:
        logger.warning("AI_API_BASE environment variable is not set. Summarization feature will be disabled.")

    # --- Error if critical Telegram vars missing ---
    if missing_vars:
        error_message = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_message)
        raise ValueError(error_message)

    # --- Type Conversion and Validation ---
    try:
        api_id = int(api_id_str)
    except (ValueError, TypeError):
        error_message = f"Invalid API_ID: '{api_id_str}'. Must be an integer."
        logger.error(error_message)
        raise ValueError(error_message) from None
    try:
        webhook_interval_minutes = int(webhook_interval_str)
        if webhook_interval_minutes <= 0:
            raise ValueError("Summary interval (WEBHOOK_INTERVAL_MINUTES) must be positive.")
    except (ValueError, TypeError):
        error_message = f"Invalid WEBHOOK_INTERVAL_MINUTES: '{webhook_interval_str}'. Must be a positive integer."
        logger.error(error_message)
        raise ValueError(error_message) from None

    # --- Create Config object ---
    config = Config(
        api_id=api_id,
        api_hash=api_hash,
        bot_name=bot_name,
        webhook_interval_minutes=webhook_interval_minutes,
        telegram_groups=telegram_groups,
        ai_api_base=ai_api_base,
        ai_api_key=ai_api_key,
        ai_model_name=ai_model_name,
        webhook_url=webhook_url,
    )

    logger.info(f"Configuration loaded successfully for bot: {config.bot_name}")
    logger.debug(f"Loaded config values (excluding sensitive): bot_name={config.bot_name}, webhook_url={config.webhook_url}, interval={config.webhook_interval_minutes}, groups={config.telegram_groups}") # Avoid logging api_id/hash

    return config

# Example usage (optional, for testing)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Create a dummy .env for testing if needed
    # with open(".env", "w") as f:
    #     f.write("API_ID=12345\n")
    #     f.write("API_HASH=abcdef123456\n")
    #     f.write("BOT_NAME=TestBot\n")
    #     f.write("WEBHOOK_URL=http://example.com/webhook\n")
    #     f.write("WEBHOOK_INTERVAL_MINUTES=30\n")
    #     f.write("TELEGRAM_GROUPS=group1, group2\n")
    try:
        cfg = load_config()
        print("Config loaded:", cfg)
    except ValueError as e:
        print(f"Error loading config: {e}")
    # finally:
        # Clean up dummy .env if created
        # if os.path.exists(".env"):
        #     os.remove(".env")
