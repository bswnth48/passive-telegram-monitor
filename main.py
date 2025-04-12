import asyncio
import logging
import uvicorn # Need uvicorn to run FastAPI
from datetime import datetime, timedelta
from telethon import TelegramClient # Import client for sending summary
from telethon.errors import UserIsBlockedError, FloodWaitError # Errors for sending message

# Configuration loading
from bot.config import load_config, Config

# Bot logic
from bot.observer import start_observer, FORWARD_TARGET_USER_ID # Import target ID
from bot.logger import initialize_db, get_messages_since # Use new logger func
from bot.summarizer import get_ai_summary # Import AI summarizer

# API logic
from api.main import app as fastapi_app # Import the FastAPI app instance

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Silence noisy uvicorn logs unless needed
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
# Potentially silence httpx logs too if they become noisy
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Summary Scheduler Task ---
async def summary_scheduler(config: Config, client: TelegramClient):
    """Periodically fetches messages, generates AI summary, and sends it to the target user."""
    if not config.ai_api_base or not config.ai_api_key:
        logger.warning("AI not configured. Summary scheduler will not run.")
        return
    if config.webhook_interval_minutes <= 0:
        logger.warning("Invalid summary interval. Scheduler will not run.")
        return

    interval_seconds = config.webhook_interval_minutes * 60
    last_check_time = datetime.utcnow() # Start checking from now

    logger.info(f"Summary scheduler started. Interval: {config.webhook_interval_minutes} minutes.")

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            current_check_time = datetime.utcnow()
            logger.info(f"Summary interval elapsed. Fetching messages since {last_check_time}...")

            # Fetch messages logged since the last check
            messages_to_summarize = await get_messages_since(last_check_time)

            if messages_to_summarize:
                logger.info(f"Found {len(messages_to_summarize)} new messages. Generating AI summary...")

                ai_summary = await get_ai_summary(config, messages_to_summarize)

                if ai_summary and not ai_summary.startswith("Error") and not ai_summary.startswith("AI summarization not configured") and not ai_summary.startswith("No new messages") :
                    logger.info("AI summary generated. Sending to target user...")
                    summary_header = f"📄 AI Summary ({last_check_time.strftime('%H:%M')} - {current_check_time.strftime('%H:%M')} UTC):\n---"
                    full_summary_message = f"{summary_header}\n{ai_summary}"

                    # Send summary to the target user via Telegram
                    try:
                        await client.send_message(
                            entity=FORWARD_TARGET_USER_ID,
                            message=full_summary_message
                        )
                        logger.info(f"Successfully sent AI summary to user {FORWARD_TARGET_USER_ID}")
                        # Update last_check_time only if summary sent successfully
                        last_check_time = current_check_time
                    except UserIsBlockedError:
                        logger.warning(f"Cannot send summary: User {FORWARD_TARGET_USER_ID} has blocked this bot/user.")
                    except FloodWaitError as e:
                        logger.warning(f"Flood wait error sending summary. Waiting {e.seconds}s.")
                        await asyncio.sleep(e.seconds + 1)
                    except Exception as e:
                        logger.error(f"Failed to send summary to user {FORWARD_TARGET_USER_ID}: {e}", exc_info=True)
                else:
                    logger.warning(f"AI summary generation failed or empty: {ai_summary}")
                    # Decide if last_check_time should be updated even on AI failure
                    # Maybe update to avoid huge backlog? For now, we don't update on failure.
            else:
                logger.info("No new messages found since last check. Skipping summary.")
                # Update time even if no messages, so we don't query increasingly large ranges
                last_check_time = current_check_time

        except asyncio.CancelledError:
            logger.info("Summary scheduler task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in summary scheduler loop: {e}", exc_info=True)
            await asyncio.sleep(60)

async def run_observer_and_scheduler(config: Config):
    """Runs the observer and scheduler, passing the client instance."""
    session_name = f"sessions/{config.bot_name.lower()}_session"
    client = TelegramClient(session_name, config.api_id, config.api_hash)
    client.app_config = config # Attach config for handler
    logger.info(f"Initializing TelegramClient for observer/scheduler: {session_name}")

    async with client:
        # Run observer and scheduler concurrently, passing the client to scheduler
        observer_task = asyncio.create_task(start_observer(client), name="TelegramObserver") # Pass client directly
        scheduler_task = asyncio.create_task(summary_scheduler(config, client), name="SummaryScheduler")

        done, pending = await asyncio.wait(
            [observer_task, scheduler_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Handle completion/cancellation (simplified)
        for task in pending:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
            except Exception: logger.exception(f"Error during cancellation of task {task.get_name()}")
        for task in done:
             if task.exception(): logger.exception(f"Task {task.get_name()} failed:", exc_info=task.exception())

async def start_observer(client: TelegramClient): # Modified to accept client
    """Registers handler and runs the client until disconnected."""
    # We assume client is connected and authorized by run_observer_and_scheduler
    client.add_event_handler(handle_new_message, events.NewMessage())
    logger.info("Registered new message handler for all messages.")
    me = await client.get_me()
    global _BOT_USER_ID
    _BOT_USER_ID = me.id
    logger.info(f"Logged in as: {me.username} (ID: {_BOT_USER_ID})")
    # Group joining logic now needs the client passed here if we move it out
    # For simplicity now, assume groups were joined elsewhere or handled manually
    logger.info("Observer running. Waiting for messages...")
    await client.run_until_disconnected()
    logger.info("Telegram client stopped.")

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

    # 4. Create Tasks for API and the combined Bot runner
    bot_runner_task = asyncio.create_task(run_observer_and_scheduler(config), name="BotRunner")
    api_task = asyncio.create_task(api_server.serve(), name="APIServer")

    logger.info("Starting API server and Bot Runner (Observer + Scheduler)...")

    # Wait for any task to complete (or fail)
    tasks = [bot_runner_task, api_task]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

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
