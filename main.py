import asyncio
import logging
import uvicorn # Need uvicorn to run FastAPI
from datetime import datetime, timedelta

# Configuration loading
from bot.config import load_config, Config

# Bot logic
from bot.observer import start_observer
from bot.logger import initialize_db, get_new_messages_summary_since # Updated logger import
from bot.webhook import send_webhook # Import webhook sender

# API logic
from api.main import app as fastapi_app # Import the FastAPI app instance

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Silence noisy uvicorn logs unless needed
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
# Potentially silence httpx logs too if they become noisy
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Webhook Scheduler Task ---
async def webhook_scheduler(config: Config):
    """Periodically fetches new message summary and sends webhook."""
    if not config.webhook_url or config.webhook_interval_minutes <= 0:
        logger.warning("Webhook URL or interval not configured/invalid. Scheduler will not run.")
        return

    interval_seconds = config.webhook_interval_minutes * 60
    last_check_time = datetime.utcnow() # Start checking from now

    logger.info(f"Webhook scheduler started. Interval: {config.webhook_interval_minutes} minutes.")

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            current_check_time = datetime.utcnow()
            logger.info(f"Webhook interval elapsed. Fetching messages since {last_check_time}...")

            # Fetch summary of messages logged since the last check
            message_summary = await get_new_messages_summary_since(last_check_time)

            if message_summary["total_new_messages"] > 0:
                logger.info(f"Found {message_summary['total_new_messages']} new messages. Sending webhook...")
                # Payload includes the summary dict directly
                webhook_payload = {
                    "type": "message_summary",
                    "data": message_summary
                }
                success = await send_webhook(config, webhook_payload)
                if success:
                    # Update last_check_time only if webhook was sent successfully
                    last_check_time = current_check_time
                else:
                    logger.warning("Webhook send failed. Will retry with same data next interval.")
            else:
                logger.info("No new messages found since last check. Skipping webhook.")
                # Update time even if no messages, so we don't query increasingly large ranges
                last_check_time = current_check_time

        except asyncio.CancelledError:
            logger.info("Webhook scheduler task cancelled.")
            break # Exit loop on cancellation
        except Exception as e:
            # Log unexpected errors in the scheduler loop but continue running
            logger.error(f"Error in webhook scheduler loop: {e}", exc_info=True)
            # Optional: Add a small delay before retrying after an error
            await asyncio.sleep(60)

async def launch_bot_and_api():
    """
    Initializes DB, loads config, and runs the Bot Observer, FastAPI server, and Webhook Scheduler concurrently.
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

    # 4. Create Tasks for Observer, API, and Scheduler
    observer_task = asyncio.create_task(start_observer(config), name="TelegramObserver")
    api_task = asyncio.create_task(api_server.serve(), name="APIServer")
    scheduler_task = asyncio.create_task(webhook_scheduler(config), name="WebhookScheduler")

    logger.info("Starting Telegram Observer, API server, and Webhook Scheduler...")

    # Wait for any task to complete (or fail)
    tasks = [observer_task, api_task, scheduler_task]
    done, pending = await asyncio.wait(
        tasks,
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
