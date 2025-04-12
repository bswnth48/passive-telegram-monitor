import logging
import asyncio # Added for potential delays
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import FloodWaitError, UserAlreadyParticipantError, ChannelsTooMuchError, ChannelInvalidError, ChannelPrivateError, InviteHashExpiredError, UserIsBlockedError
# Peer types for type checking
from telethon.tl.types import PeerUser, PeerChat, PeerChannel
# Import specific media types for checking
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage

from .config import Config
from .logger import log_message # Import the logging function

logger = logging.getLogger(__name__)

# Define the target user ID for forwarding messages
# Replace with the actual User ID where messages should be sent
FORWARD_TARGET_USER_ID = 1137119534 # Your User ID

async def handle_new_message(event):
    """Handles incoming messages, logs rich data, and forwards the original message."""
    sender = None # Initialize sender
    message = event.message # Get the message object
    try:
        # 1. Get Sender Info (for logging)
        sender = await event.get_sender()
        sender_id = getattr(sender, 'id', None)
        sender_username = getattr(sender, 'username', None)
        sender_first_name = getattr(sender, 'first_name', None)
        sender_last_name = getattr(sender, 'last_name', None)
        sender_is_bot = getattr(sender, 'bot', False)

        # 2. Get Chat Info (for logging)
        chat = await event.get_chat()
        chat_id = event.chat_id
        chat_title = getattr(chat, 'title', None) # Title for groups/channels
        chat_username = getattr(chat, 'username', None)

        # Determine chat type (for logging)
        if isinstance(event.peer_id, PeerUser):
            chat_type = 'user'
            # For DMs, use sender's name as title if chat title is None
            if not chat_title and sender:
                 chat_title = f"{sender_first_name or ''} {sender_last_name or ''}".strip()
        elif isinstance(event.peer_id, PeerChat):
            chat_type = 'group' # Legacy group
        elif isinstance(event.peer_id, PeerChannel):
            # Could be supergroup or channel - check 'broadcast' flag
            chat_type = 'channel' if getattr(chat, 'broadcast', False) else 'group'
        else:
            chat_type = 'unknown'

        # 3. Get Message Info (including entities and media)
        message_id = message.id
        timestamp = message.date # Already a datetime object
        text = message.text # Or message.message
        entities = message.entities # Can be None
        media = message.media

        # Process media information
        media_type = None
        media_info = None
        if isinstance(media, MessageMediaPhoto):
            media_type = 'photo'
            # Extract basic info, avoiding full object serialization
            media_info = {
                'id': media.photo.id,
                'access_hash': media.photo.access_hash,
                'has_stickers': bool(media.photo.has_stickers),
                # 'sizes': [s.type for s in media.photo.sizes] # Example: can add more if needed
            }
        elif isinstance(media, MessageMediaDocument):
            media_type = 'document'
            doc_attrs = {attr.CONSTRUCTOR_ID: attr for attr in media.document.attributes}
            filename_attr = doc_attrs.get(b'\x15\xb2\x9d\x28') # DocumentAttributeFilename
            media_info = {
                'id': media.document.id,
                'access_hash': media.document.access_hash,
                'mime_type': media.document.mime_type,
                'size': media.document.size,
                'filename': getattr(filename_attr, 'file_name', None),
                # Add other attributes like video/audio duration if needed
            }
            # Refine media type based on mime type
            if media.document.mime_type:
                if media.document.mime_type.startswith('video/'):
                    media_type = 'video'
                elif media.document.mime_type.startswith('audio/'):
                    media_type = 'audio'
                elif media.document.mime_type == 'image/webp': # Stickers are often webp documents
                     # Check for DocumentAttributeSticker
                     if b'\xaf\`\xf5\x06' in doc_attrs:
                         media_type = 'sticker'
        elif isinstance(media, MessageMediaWebPage):
            media_type = 'webpage'
            media_info = {
                'url': getattr(media.webpage, 'url', None),
                'display_url': getattr(media.webpage, 'display_url', None),
                'site_name': getattr(media.webpage, 'site_name', None),
                'title': getattr(media.webpage, 'title', None),
                # 'description': getattr(media.webpage, 'description', None)
            }
        # Add elif blocks for other media types (MessageMediaContact, Geo, etc.) if needed

        # Convert Telethon entities to simpler list of dicts for JSON serialization
        serializable_entities = None
        if entities:
            serializable_entities = []
            for entity in entities:
                entity_dict = entity.to_dict()
                # Remove any non-standard keys if necessary, e.g., '_'
                entity_dict.pop('_', None)
                serializable_entities.append(entity_dict)

        # Basic console logging (optional, can be removed later)
        logger.info(
            f"New message in {chat_type} '{chat_title or chat_username}' (ID: {chat_id}) "
            f"from user '{sender_username or sender_id}' (ID: {sender_id}): "
            f"MsgID {message_id}"
        )

        # 4. Log to Database
        await log_message(
            chat_id=chat_id,
            chat_type=chat_type,
            chat_title=chat_title,
            chat_username=chat_username,
            sender_id=sender_id,
            sender_username=sender_username,
            sender_first_name=sender_first_name,
            sender_last_name=sender_last_name,
            sender_is_bot=sender_is_bot,
            message_id=message_id,
            timestamp=timestamp,
            text=text,
            entities=serializable_entities, # Pass the serializable list
            media_type=media_type,
            media_info=media_info
        )

        # 5. Forward the *original* message
        if FORWARD_TARGET_USER_ID and event.client:
            try:
                await event.client.forward_messages(
                    entity=FORWARD_TARGET_USER_ID,  # Who to forward to (your User ID)
                    messages=message,           # The specific message object to forward
                    from_peer=event.chat_id      # The chat where the message originated
                )
                logger.debug(f"Forwarded message {message_id} from {chat_id} to {FORWARD_TARGET_USER_ID}")

            except UserIsBlockedError:
                logger.warning(f"Cannot forward message: User {FORWARD_TARGET_USER_ID} has blocked this bot/user.")
            except FloodWaitError as e:
                 logger.warning(f"Flood wait error while forwarding message. Waiting {e.seconds} seconds.")
                 await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                # Catch potential errors during forwarding (e.g., message deleted before forwarding)
                logger.error(f"Error forwarding message {message_id} from {chat_id}: {e}", exc_info=True)
        elif not event.client:
            logger.warning("event.client not available, cannot forward message.")

    except Exception as e:
        # Catch errors during message processing/logging itself
        logger.error(f"Error processing message event {getattr(message, 'id', '?')}: {e}", exc_info=True)

    # TODO: Implement logic to check against webhook triggers based on the logged data or event

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
