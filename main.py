import asyncio
import logging

# Configuration loading
from bot.config import load_config, Config

# Bot logic
from bot.observer import start_observer
from bot.logger import initialize_db # Import the initializer

# Placeholder for API logic
# from api import main as api_main # Assuming FastAPI app is in api/main.py

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def launch_bot():
    """
    Main entry point to launch the bot instance based on environment configuration.
    """
    # 1. Initialize Database
    try:
        await initialize_db()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}. Cannot proceed.", exc_info=True)
        return # Stop if DB init fails

    # 2. Load Configuration
    config: Config
    try:
        config = load_config()
        logger.info(f"Configuration loaded for bot: {config.bot_name}")
    except ValueError as e:
        logger.error(f"Failed to load configuration: {e}")
        return # Exit if config fails
    except Exception as e:
        logger.exception("An unexpected error occurred during configuration loading:", exc_info=e)
        return

    logger.info(f"Launching bot instance: {config.bot_name}")

    # 3. Start Observer
    try:
        # Start the Telegram observer
        await start_observer(config)
        logger.info(f"Observer for {config.bot_name} finished.")
    except Exception as e:
        logger.exception(f"An error occurred while running the observer for {config.bot_name}:", exc_info=e)

    # TODO: Optionally, start the FastAPI server if needed as part of the launch
    # uvicorn.run(api_main.app, host="0.0.0.0", port=8000) # Example

    logger.info(f"Bot instance {config.bot_name} launch sequence complete.")
    # The start_observer function now handles the main running loop
    # No longer need asyncio.Future() here


if __name__ == "__main__":
    # The bot name is now determined by the environment config loaded in launch_bot
    try:
        asyncio.run(launch_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped manually.")
    except Exception as e:
        # This top-level exception might catch issues during asyncio.run itself
        logger.exception("An error occurred during bot execution:", exc_info=e)
