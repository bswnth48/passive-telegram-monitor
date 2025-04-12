import asyncio
import logging
import uvicorn # Need uvicorn to run FastAPI

# Configuration loading
from bot.config import load_config, Config

# Bot logic
from bot.observer import start_observer
from bot.logger import initialize_db # Import the initializer

# API logic
from api.main import app as fastapi_app # Import the FastAPI app instance

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Silence noisy uvicorn logs unless needed
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

async def launch_bot_and_api():
    """
    Initializes DB, loads config, and runs the Bot Observer and FastAPI server concurrently.
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

    # 3. Configure Uvicorn Server
    # Note: Consider making host/port configurable via .env later
    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host="0.0.0.0",
        port=8000,
        log_level="info", # Control uvicorn's internal logging level
        # loop="asyncio" # Usually inferred
    )
    api_server = uvicorn.Server(uvicorn_config)

    # 4. Run Observer and API concurrently
    observer_task = asyncio.create_task(start_observer(config), name="TelegramObserver")
    api_task = asyncio.create_task(api_server.serve(), name="APIServer")

    logger.info("Starting Telegram Observer and API server...")

    # Wait for either task to complete (or fail)
    # Using asyncio.wait to handle completion/cancellation gracefully
    done, pending = await asyncio.wait(
        [observer_task, api_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    logger.info("One of the main tasks finished. Initiating shutdown.")

    # Check for exceptions in completed tasks
    for task in done:
        try:
            result = task.result()
            logger.info(f"Task {task.get_name()} finished cleanly with result: {result}")
        except Exception:
            logger.exception(f"Task {task.get_name()} failed:")

    # Cancel pending tasks
    for task in pending:
        logger.info(f"Cancelling pending task: {task.get_name()}")
        task.cancel()
        try:
            await task # Allow cancellation to propagate
        except asyncio.CancelledError:
            logger.info(f"Task {task.get_name()} cancelled successfully.")
        except Exception:
            logger.exception(f"Error during cancellation of task {task.get_name()}:")

    logger.info(f"Bot instance {config.bot_name} shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(launch_bot_and_api())
    except KeyboardInterrupt:
        logger.info("Shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        logger.exception("An error occurred during bot execution:", exc_info=e)
    finally:
        logger.info("Application finished.")
