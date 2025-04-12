import logging
import asyncio # Added for potential delays
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import FloodWaitError, UserAlreadyParticipantError, ChannelsTooMuchError, ChannelInvalidError, ChannelPrivateError, InviteHashExpiredError, UserIsBlockedError
# Peer types for type checking
from telethon.tl.types import PeerUser, PeerChat, PeerChannel
# Import specific media types for checking
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from datetime import datetime, date, time # Import date/time for summary command

from .config import Config
from .logger import log_message, mark_message_forwarded, get_unforwarded_summary, get_messages_since
from .summarizer import get_ai_summary

logger = logging.getLogger(__name__)

# Define the target user ID for forwarding messages
# Replace with the actual User ID where messages should be sent
FORWARD_TARGET_USER_ID = 1137119534 # Your User ID

# --- State Variable --- (Consider moving to a class if state grows)
is_forwarding_active = True # Start with forwarding enabled

# Store the bot's own user ID to prevent self-processing
_BOT_USER_ID = None

async def handle_new_message(event):
    """Handles incoming messages: logs, processes commands, forwards notifications if active."""
    global is_forwarding_active, _BOT_USER_ID

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

        # --- Command Processing --- (Only if message is from the target user)
        if sender_id == FORWARD_TARGET_USER_ID:
            command_text = text.strip().lower() if text else ""
            if command_text == '/stop_forwarding':
                if is_forwarding_active:
                    is_forwarding_active = False
                    await event.reply("OK. Message notifications stopped.")
                    logger.info(f"Forwarding stopped by user {FORWARD_TARGET_USER_ID}.")
                else:
                    await event.reply("Notifications are already stopped.")
                return # Stop processing after handling command

            elif command_text == '/start_forwarding':
                if not is_forwarding_active:
                    is_forwarding_active = True
                    logger.info(f"Forwarding started by user {FORWARD_TARGET_USER_ID}.")
                    # Get summary of missed messages
                    summary_data = await get_unforwarded_summary()
                    if summary_data:
                        summary_lines = ["Missed message summary:"]
                        for chat, count in summary_data.items():
                            summary_lines.append(f"- {chat}: {count} unread")
                        summary_text = "\n".join(summary_lines)
                    else:
                        summary_text = "No unread messages found since forwarding stopped."
                    await event.reply(f"OK. Message notifications started.\n\n{summary_text}")
                else:
                    await event.reply("Notifications are already active.")
                return # Stop processing after handling command

            elif command_text == '/summary_today':
                 await event.reply("Generating today's summary from AI... please wait.")
                 logger.info(f"Summary requested by user {FORWARD_TARGET_USER_ID}.")
                 # Calculate start of today
                 today_start = datetime.combine(date.today(), time.min)
                 # Use get_messages_since with today's start time
                 messages_to_summarize = await get_messages_since(today_start)

                 client_config = getattr(event.client, 'app_config', None)
                 if client_config:
                     ai_summary = await get_ai_summary(client_config, messages_to_summarize)
                     if ai_summary and not ai_summary.startswith("Error") and not ai_summary.startswith("AI summarization not configured") and not ai_summary.startswith("No new messages") :
                         await event.reply(f"AI Summary for Today:\n---\n{ai_summary}")
                     else:
                         await event.reply(f"Could not generate AI summary: {ai_summary}") # Show reason
                 else:
                     await event.reply("Error: Could not access bot configuration for AI settings.")
                 return # Stop processing after handling command
        # --- End Command Processing ---

        # --- Prevent processing bot's own outgoing messages (unless it's a command) ---
        # We check _BOT_USER_ID which should be set when the observer starts
        if _BOT_USER_ID is not None and sender_id == _BOT_USER_ID:
             # Allow processing commands sent by the bot owner to self, handled above.
             # Ignore other self-sent messages.
            logger.debug(f"Ignoring self-sent message {message.id}")
            return

        # 5. Send Custom Formatted Notification
        if is_forwarding_active and FORWARD_TARGET_USER_ID and event.client:
            notification_sent = False
            try:
                # Construct the custom message string
                sender_display = f"{sender_first_name or ''} {sender_last_name or ''}".strip()
                sender_display = sender_display or sender_username or f"ID:{sender_id}" if sender_id else "(Unknown Sender)"
                if sender_is_bot:
                    sender_display += " [Bot]"

                chat_display = chat_title or chat_username or f"ID:{chat_id}"

                # Add indicators for links/media
                content_indicators = []
                if serializable_entities:
                    if any(e.get('type') == 'url' or e.get('type') == 'text_link' for e in serializable_entities):
                         content_indicators.append("🔗Links")
                if media_type:
                    content_indicators.append(f"🖼️Media ({media_type})")
                indicator_str = f" [{', '.join(content_indicators)}]" if content_indicators else ""

                forward_header = f"✉️ Received Msg{indicator_str}\nFrom: {chat_display} ({chat_type})\nBy: {sender_display}\nTime: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\nRef: {message_id} / {chat_id}\n---"

                # Include text, or placeholder if only media
                forward_body = text or f"(No text content - Media Type: {media_type or 'Unknown'})"
                forward_message = f"{forward_header}\n{forward_body}"

                # Limit message length
                max_len = 4000
                if len(forward_message) > max_len:
                    forward_message = forward_message[:max_len] + "... (truncated)"

                # Use send_message instead of forward_messages
                await event.client.send_message(
                    entity=FORWARD_TARGET_USER_ID,
                    message=forward_message,
                    link_preview=False # Disable previews for cleaner look
                )
                notification_sent = True # Mark as successful
                logger.debug(f"Sent notification for message {message_id} from {chat_id} to {FORWARD_TARGET_USER_ID}")

            except UserIsBlockedError:
                logger.warning(f"Cannot send notification: User {FORWARD_TARGET_USER_ID} has blocked this bot/user.")
            except FloodWaitError as e:
                 logger.warning(f"Flood wait error while sending notification. Waiting {e.seconds} seconds.")
                 await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                # Catch potential errors during forwarding (e.g., message deleted before forwarding)
                logger.error(f"Error sending notification for message {message_id} from {chat_id}: {e}", exc_info=True)

            # 6. Mark message as forwarded in DB if notification was sent
            if notification_sent:
                await mark_message_forwarded(chat_id, message_id)
        elif not event.client:
            logger.warning("event.client not available, cannot send notification.")

    except Exception as e:
        # Catch errors during message processing/logging itself
        logger.error(f"Error processing message event {getattr(message, 'id', '?')}: {e}", exc_info=True)

    # TODO: Implement logic to check against webhook triggers based on the logged data or event

async def start_observer(client: TelegramClient):
    """Registers handler and runs the client until disconnected."""
    # We assume client is connected and authorized by the calling function

    # Register the event handler for new messages
    client.add_event_handler(handle_new_message, events.NewMessage())
    logger.info("Registered new message handler for all messages.")

    # Store bot's own ID if not already done (might be redundant but safe)
    global _BOT_USER_ID
    if _BOT_USER_ID is None:
        try:
            me = await client.get_me()
            if me:
                _BOT_USER_ID = me.id
                logger.info(f"Observer confirmed login as: {me.username} (ID: {_BOT_USER_ID})")
            else:
                 logger.warning("Could not get self user in start_observer, self-checks might fail.")
        except Exception as e:
            logger.error(f"Error getting self user in start_observer: {e}")

    # --- Group Joining Logic --- (Moved back here)
    config = client.app_config # Get config attached to client
    if config.telegram_groups:
        logger.info(f"Attempting to join configured groups: {config.telegram_groups}")
        joined_groups = 0
        failed_groups = []
        for group_identifier in config.telegram_groups:
            try:
                logger.debug(f"Attempting to join: {group_identifier}")
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
                logger.error("Cannot join more groups. Account limit reached.")
                failed_groups.append(group_identifier)
            except FloodWaitError as e:
                logger.warning(f"Flood wait joining {group_identifier}. Waiting {e.seconds}s.")
                failed_groups.append(group_identifier)
                await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                logger.error(f"Failed to join group {group_identifier}: {e}", exc_info=True)
                failed_groups.append(group_identifier)
            await asyncio.sleep(1)

        logger.info(f"Finished group joining. Joined/In {joined_groups} groups.")
        if failed_groups:
            logger.warning(f"Failed to join/process: {failed_groups}")
    else:
        logger.warning("No TELEGRAM_GROUPS configured.")
    # --- End Group Joining Logic ---

    logger.info("Observer ready. Waiting for messages...")
    try:
        await client.run_until_disconnected()
    finally:
        logger.info("Observer client run_until_disconnected finished.")
