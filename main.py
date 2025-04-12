import asyncio
import logging
import uvicorn # Need uvicorn to run FastAPI
from datetime import datetime, timedelta
from telethon import TelegramClient # Import client for sending summary
from telethon.errors import UserIsBlockedError, FloodWaitError # Errors for sending message

# Configuration loading
from bot.config import load_config, Config

# Bot logic
from bot.observer import start_observer # Only need start_observer here
# Logger functions needed by scheduler or command handler (which runs via observer)
from bot.logger import initialize_db, get_messages_since, get_all_notification_target_ids
from bot.summarizer import get_ai_summary # Import AI summarizer
from bot.webhook import send_webhook # Re-import webhook sender

# API logic
from api.main import app as fastapi_app # Import the FastAPI app instance

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Silence noisy uvicorn logs unless needed
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
# Potentially silence httpx logs too if they become noisy
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Combined Scheduler Task ---
async def periodic_task_scheduler(config: Config, client: TelegramClient):
    """Periodically performs scheduled tasks: AI summary and optional webhook send."""

    # Check if any scheduled task is possible
    ai_enabled = config.ai_api_base and config.ai_api_key
    webhook_enabled = bool(config.webhook_url)
    if not ai_enabled and not webhook_enabled:
        logger.warning("Neither AI nor Webhook is configured. Scheduler will not run.")
        return
    if config.webhook_interval_minutes <= 0:
        logger.warning("Invalid interval. Scheduler will not run.")
        return

    interval_seconds = config.webhook_interval_minutes * 60
    last_check_time = datetime.utcnow()

    logger.info(f"Periodic task scheduler started. Interval: {config.webhook_interval_minutes} minutes. AI: {ai_enabled}, Webhook: {webhook_enabled}")

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            current_check_time = datetime.utcnow()
            logger.info(f"Scheduler interval elapsed. Fetching messages since {last_check_time}...")

            # Fetch messages logged since the last check
            messages_since_last = await get_messages_since(last_check_time)

            if messages_since_last:
                logger.info(f"Found {len(messages_since_last)} new messages.")

                # --- Task 1: AI Summary (if enabled) ---
                ai_summary_result = None
                if ai_enabled:
                    logger.info("Generating AI summary...")
                    ai_summary_result = await get_ai_summary(config, messages_since_last)
                    if not ai_summary_result or ai_summary_result.startswith("Error") or ai_summary_result.startswith("AI") or ai_summary_result.startswith("No new messages"):
                        logger.warning(f"AI summary generation failed or empty: {ai_summary_result}")
                        ai_summary_result = None # Ensure it's None if failed
                    else:
                        logger.info("AI summary generated successfully.")
                else:
                    logger.debug("AI summary disabled by configuration.")

                # --- Send AI Summary to Targets (if generated) ---
                if ai_summary_result:
                    summary_header = f"📄 AI Summary ({last_check_time.strftime('%H:%M')} - {current_check_time.strftime('%H:%M')} UTC):\n---"
                    full_summary_message = f"{summary_header}\n{ai_summary_result}"
                    target_ids = await get_all_notification_target_ids()
                    logger.info(f"Sending AI summary to {len(target_ids)} targets...")
                    for target_id in target_ids:
                        try:
                            await client.send_message(entity=target_id, message=full_summary_message)
                            logger.debug(f"Sent summary to target {target_id}")
                        except (UserIsBlockedError, FloodWaitError) as e:
                            logger.warning(f"Error sending summary to target {target_id}: {e}")
                            if isinstance(e, FloodWaitError): await asyncio.sleep(e.seconds + 1)
                        except Exception as e:
                            logger.error(f"Failed to send summary to target {target_id}: {e}", exc_info=True)

                # --- Task 2: External Webhook (if enabled) ---
                if webhook_enabled:
                    logger.info(f"Sending message batch to external webhook: {config.webhook_url}")
                    # The payload for the webhook is the raw list of message dicts
                    await send_webhook(config, messages_since_last)
                else:
                    logger.debug("External webhook disabled by configuration.")

                # Update last_check_time regardless of individual task success/failure
                # This prevents the time window from growing indefinitely if one task fails
                last_check_time = current_check_time

            else:
                logger.info("No new messages found since last check.")
                last_check_time = current_check_time # Still update time

        except asyncio.CancelledError:
            logger.info("Periodic task scheduler cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in periodic scheduler loop: {e}", exc_info=True)
            await asyncio.sleep(60) # Wait a bit after an unexpected error

# --- Combined Bot Runner ---
async def run_observer_and_scheduler(config: Config):
    """Connects the client and runs the observer and scheduler concurrently."""
    session_name = f"sessions/{config.bot_name.lower()}_session"
    client = TelegramClient(session_name, config.api_id, config.api_hash)
    client.app_config = config # Attach config for handler access
    logger.info(f"Initializing TelegramClient: {session_name}")

    # Retry connection logic needs to be here before starting tasks
    max_retries = 3
    retry_delay = 5
    connected = False
    for attempt in range(max_retries):
        try:
            logger.debug(f"Connection attempt {attempt + 1}/{max_retries}...")
            await client.connect()
            if await client.is_user_authorized():
                logger.info("Client connected and authorized.")
                connected = True
                break
            else:
                # This case needs user interaction (code/password)
                # For now, log and proceed assuming manual login happens or session is valid
                logger.warning("Client connected but not authorized. Manual login might be required.")
                connected = True # Treat as connected for now, observer might fail later if still unauthorized
                break
        except ConnectionError as e:
            logger.error(f"Connection attempt {attempt + 1} failed: {e}")
            if attempt + 1 == max_retries: break
            await asyncio.sleep(retry_delay)
        except Exception as e:
             logger.exception(f"Unexpected error during connection attempt {attempt + 1}:", exc_info=e)
             if attempt + 1 == max_retries: break
             await asyncio.sleep(retry_delay)

    if not connected:
        logger.critical("Failed to connect to Telegram after multiple retries. Exiting bot runner.")
        return

    # Run tasks within the client context manager
    try:
        async with client:
            observer_task = asyncio.create_task(start_observer(client), name="TelegramObserver")
            scheduler_task = asyncio.create_task(periodic_task_scheduler(config, client), name="PeriodicScheduler")

            done, pending = await asyncio.wait(
                [observer_task, scheduler_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            # Handle completion/cancellation
            for task in pending: task.cancel(); await asyncio.sleep(0) # Allow cancellation
            for task in done:
                if task.exception(): logger.exception(f"Task {task.get_name()} failed:", exc_info=task.exception())

    except Exception as e:
        logger.exception("Error within the main client context manager:", exc_info=e)
    finally:
        logger.info("Bot runner task finished.")
        if client.is_connected():
            await client.disconnect()
            logger.info("Telegram client disconnected.")

async def launch_bot_and_api():
    """Initializes DB, loads config, runs API and the combined observer/scheduler."""
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

    # 4. Create Tasks for API and the Bot runner
    bot_runner_task = asyncio.create_task(run_observer_and_scheduler(config), name="BotRunner")
    api_task = asyncio.create_task(api_server.serve(), name="APIServer")

    logger.info("Starting API server and Bot Runner (Observer + Scheduler)...")
    tasks = [bot_runner_task, api_task]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    logger.info("One of the main tasks finished. Initiating shutdown.")
    # Cleanup
    for task in pending: task.cancel(); await asyncio.sleep(0) # Allow cancellation
    for task in done:
        if task.exception(): logger.exception(f"Task {task.get_name()} failed:", exc_info=task.exception())

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
