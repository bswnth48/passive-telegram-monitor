import logging
from telethon import TelegramClient, events
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
    """Initializes and starts the Telegram client observer."""
    session_name = f"sessions/{config.bot_name.lower()}_session"
    logger.info(f"Initializing TelegramClient with session: {session_name}")

    client = TelegramClient(session_name, config.api_id, config.api_hash)

    # Register the event handler for new messages
    client.add_event_handler(handle_new_message, events.NewMessage())
    logger.info("Registered new message handler.")

    async with client:
        logger.info(f"Telegram client started for bot: {config.bot_name}")
        me = await client.get_me()
        logger.info(f"Logged in as: {me.username} (ID: {me.id})")

        # Log the groups we are supposed to monitor (joining logic TBD)
        if config.telegram_groups:
            logger.info(f"Configured to monitor groups: {config.telegram_groups}")
            # TODO: Implement logic to actually join these groups if not already joined.
            # Example (requires more logic for checking/joining):
            # for group_link in config.telegram_groups:
            #     try:
            #         await client(JoinChannelRequest(group_link))
            #         logger.info(f"Joined or already in group: {group_link}")
            #     except Exception as e:
            #         logger.error(f"Failed to join group {group_link}: {e}")
        else:
            logger.warning("No TELEGRAM_GROUPS configured. Bot will only listen to existing chats/DMs.")

        logger.info("Observer running. Waiting for messages...")
        await client.run_until_disconnected()

    logger.info("Telegram client stopped.")
