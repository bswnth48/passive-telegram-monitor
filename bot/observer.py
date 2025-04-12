import logging
import asyncio # Added for potential delays
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import FloodWaitError, UserAlreadyParticipantError, ChannelsTooMuchError, ChannelInvalidError, ChannelPrivateError, InviteHashExpiredError
from .config import Config

logger = logging.getLogger(__name__)

async def handle_new_message(event):
    """Handles incoming messages."""
    # Basic logging for now. More detailed logging/processing will be added later.
    sender = await event.get_sender()
    chat = await event.get_chat()
    logger.info(
        f"New message in chat '{getattr(chat, 'title', chat.id)}' (ID: {chat.id}) "
        f"from user '{getattr(sender, 'username', sender.id)}' (ID: {sender.id}): "
        f"Message ID {event.message.id}"
    )
    # TODO: Implement data extraction and logging via bot.logger
    # TODO: Implement logic to check against webhook triggers

async def start_observer(config: Config):
    """Initializes, starts the Telegram client, joins configured groups, and observes."""
    session_name = f"sessions/{config.bot_name.lower()}_session"
    logger.info(f"Initializing TelegramClient with session: {session_name}")

    # Retry logic parameters
    max_retries = 3
    retry_delay = 5 # seconds

    # Connect and retry if needed
    client = TelegramClient(session_name, config.api_id, config.api_hash)
    for attempt in range(max_retries):
        try:
            await client.connect()
            if await client.is_user_authorized():
                logger.info("Client connected and authorized.")
                break # Exit loop if successful
            else:
                logger.warning("Client connected but not authorized. Manual login might be required.")
                # Depending on setup, might need to prompt for code/password here or handle externally
                # For now, we assume session is valid or manual intervention happens
                break
        except ConnectionError as e:
            logger.error(f"Connection attempt {attempt + 1} failed: {e}")
            if attempt + 1 == max_retries:
                logger.error("Max connection retries reached. Exiting observer.")
                return
            logger.info(f"Retrying connection in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logger.exception(f"An unexpected error occurred during connection attempt {attempt + 1}:", exc_info=e)
            if attempt + 1 == max_retries:
                 logger.error("Max connection retries reached due to unexpected error. Exiting observer.")
                 return
            await asyncio.sleep(retry_delay)
    else:
        # This else block executes if the loop finishes without a break (i.e., all retries failed)
        logger.error("Failed to connect to Telegram after multiple attempts.")
        return

    # Register the event handler for new messages
    client.add_event_handler(handle_new_message, events.NewMessage())
    logger.info("Registered new message handler.")

    # Start the client context manager
    async with client:
        logger.info(f"Telegram client started for bot: {config.bot_name}")
        me = await client.get_me()
        logger.info(f"Logged in as: {me.username} (ID: {me.id})")

        # Join configured groups
        if config.telegram_groups:
            logger.info(f"Attempting to join configured groups: {config.telegram_groups}")
            joined_groups = 0
            failed_groups = []
            for group_identifier in config.telegram_groups:
                try:
                    logger.debug(f"Attempting to join: {group_identifier}")
                    # Ensure we have the entity before trying to join
                    # This handles usernames, t.me links, invite links, etc.
                    entity = await client.get_entity(group_identifier)
                    await client(JoinChannelRequest(entity))
                    logger.info(f"Successfully joined or already in group: {group_identifier} (ID: {entity.id})")
                    joined_groups += 1
                except UserAlreadyParticipantError:
                    logger.info(f"Already a participant in: {group_identifier}")
                    joined_groups += 1
                except (ChannelInvalidError, ChannelPrivateError, InviteHashExpiredError, ValueError) as e:
                    logger.warning(f"Cannot join group '{group_identifier}': {type(e).__name__} - {e}. Might be private, invalid link, or require invite.")
                    failed_groups.append(group_identifier)
                except ChannelsTooMuchError:
                    logger.error("Cannot join more groups. Account has reached Telegram's limit.")
                    failed_groups.append(group_identifier) # Add to failed list and continue trying others if needed
                    # Optionally break here if desired
                except FloodWaitError as e:
                    logger.warning(f"Flood wait error while trying to join {group_identifier}. Waiting for {e.seconds} seconds.")
                    failed_groups.append(group_identifier) # Mark as failed for this run
                    await asyncio.sleep(e.seconds + 1) # Wait and add a buffer
                except Exception as e:
                    logger.error(f"Failed to join group {group_identifier} due to unexpected error: {e}", exc_info=True)
                    failed_groups.append(group_identifier)
                await asyncio.sleep(1) # Small delay between join attempts to be safe

            logger.info(f"Finished group joining process. Successfully joined/already in {joined_groups} groups.")
            if failed_groups:
                logger.warning(f"Failed to join or process the following groups: {failed_groups}")
        else:
            logger.warning("No TELEGRAM_GROUPS configured. Bot will only listen to existing chats/DMs.")

        logger.info("Observer running. Waiting for messages...")
        await client.run_until_disconnected()

    logger.info("Telegram client stopped.")
