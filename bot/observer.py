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
from .logger import (
    log_message, mark_message_forwarded, get_unforwarded_summary, get_messages_since,
    add_monitored_chat, remove_monitored_chat, list_monitored_chats,
    is_chat_monitored, is_any_chat_monitored, clear_monitored_chats,
    # New target functions
    add_notification_target, remove_notification_target, list_notification_targets,
    get_all_notification_target_ids, OWNER_USER_ID # Need owner ID for checks
)
from .summarizer import get_ai_summary

logger = logging.getLogger(__name__)

# FORWARD_TARGET_USER_ID constant is no longer the primary control, use OWNER_USER_ID instead
_BOT_USER_ID = None
is_forwarding_active = True

async def handle_new_message(event):
    """Handles incoming messages: logs, processes commands, forwards notifications if active."""
    global is_forwarding_active, _BOT_USER_ID

    sender = None
    message = event.message
    try:
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

        # --- Command Processing --- (Only if message is from the OWNER user)
        if sender_id == OWNER_USER_ID:
            parts = text.strip().split(maxsplit=1) if text else []
            command = parts[0].lower() if parts else ""
            args = parts[1] if len(parts) > 1 else ""

            if command == '/stop_forwarding':
                if is_forwarding_active:
                    is_forwarding_active = False
                    await event.reply("OK. Message notifications stopped.")
                    logger.info(f"Forwarding stopped by user {OWNER_USER_ID}.")
                else:
                    await event.reply("Notifications are already stopped.")
                return # Stop processing after handling command

            elif command == '/start_forwarding':
                if not is_forwarding_active:
                    is_forwarding_active = True
                    logger.info(f"Forwarding started by user {OWNER_USER_ID}.")
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

            elif command == '/summary_today':
                 await event.reply("Generating today's summary from AI... please wait.")
                 logger.info(f"Summary requested by user {OWNER_USER_ID}.")
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

            # --- New Monitor Commands ---
            elif command == '/monitor_add':
                if not args:
                    await event.reply("Usage: /monitor_add <chat_id or username/link>")
                    return
                try:
                    target_chat = await event.client.get_entity(args)
                    await add_monitored_chat(target_chat.id, getattr(target_chat, 'title', None), getattr(target_chat, 'username', None))
                    await event.reply(f"OK. Added chat '{getattr(target_chat, 'title', args)}' (ID: {target_chat.id}) to monitor list.")
                except ValueError:
                    await event.reply(f"Error: Could not find chat '{args}'. Please provide a valid ID, username, or link.")
                except Exception as e:
                    await event.reply(f"Error adding chat: {e}")
                    logger.error(f"Error in /monitor_add: {e}", exc_info=True)
                return

            elif command == '/monitor_remove':
                if not args:
                    await event.reply("Usage: /monitor_remove <chat_id or username/link>")
                    return
                try:
                    # Try resolving as int first, then as entity
                    try:
                        chat_id_to_remove = int(args)
                        removed = await remove_monitored_chat(chat_id_to_remove)
                    except ValueError:
                        target_chat = await event.client.get_entity(args)
                        removed = await remove_monitored_chat(target_chat.id)

                    if removed:
                        await event.reply(f"OK. Removed chat '{args}' from monitor list.")
                    else:
                        await event.reply(f"Chat '{args}' was not found in the monitor list.")
                except ValueError:
                     await event.reply(f"Error: Could not find chat '{args}'. Please provide a valid ID, username, or link.")
                except Exception as e:
                    await event.reply(f"Error removing chat: {e}")
                    logger.error(f"Error in /monitor_remove: {e}", exc_info=True)
                return

            elif command == '/monitor_list':
                monitored = await list_monitored_chats()
                if monitored:
                    lines = ["Currently Monitored Chats:"]
                    for chat in monitored:
                        display = chat['title'] or chat['username'] or f"ID:{chat['chat_id']}"
                        lines.append(f"- {display} (ID: {chat['chat_id']})")
                    await event.reply("\n".join(lines))
                else:
                    await event.reply("No chats are specifically monitored. All incoming messages are processed.")
                return

            # --- New Clear Command ---
            elif command == '/monitor_clear':
                deleted_count = await clear_monitored_chats()
                if deleted_count >= 0:
                    await event.reply(f"OK. Cleared {deleted_count} monitored chats. Now monitoring all chats.")
                else:
                    await event.reply("Error clearing monitored chats list.")
                return

            # --- New Help Command ---
            elif command == '/help':
                help_text = """**Available Commands (Owner Only):**

**Notifications:**
`/stop_forwarding` - Pause sending all notifications.
`/start_forwarding` - Resume notifications.
`/notify_add <ID/user>` - Add user to receive notifications/summaries.
`/notify_remove <ID/user>` - Remove user from receiving.
`/notify_list` - List users receiving notifications.

**Monitoring Scope:**
`/monitor_add <ID/user/link>` - Monitor only this chat.
`/monitor_remove <ID/user/link>` - Stop monitoring this chat.
`/monitor_list` - List monitored chats.
`/monitor_clear` - Monitor all chats again.

**Summarization:**
`/summary_today` - Get AI summary of today's messages.

**Help:**
`/help` - Show this help message.
"""
                await event.reply(help_text, parse_mode='md')
                return

            # --- New Notify Commands ---
            elif command == '/notify_add':
                if not args:
                    await event.reply("Usage: /notify_add <user_id or username>")
                    return
                try:
                    target_user = await event.client.get_entity(args)
                    if not isinstance(target_user, PeerUser) and not getattr(target_user, 'user_id', None):
                         await event.reply("Error: Please provide a valid user ID or username.")
                         return
                    user_id = target_user.id if hasattr(target_user, 'id') else target_user.user_id
                    username = getattr(target_user, 'username', None)
                    first_name = getattr(target_user, 'first_name', None)

                    success = await add_notification_target(user_id, username, first_name)
                    if success:
                         await event.reply(f"OK. Added notification target: {first_name or username or user_id} (ID: {user_id})")
                    else:
                         await event.reply(f"User {user_id} is the owner and cannot be added again.")
                except ValueError:
                    await event.reply(f"Error: Could not find user '{args}'.")
                except Exception as e:
                    await event.reply(f"Error adding notification target: {e}")
                return

            elif command == '/notify_remove':
                if not args:
                    await event.reply("Usage: /notify_remove <user_id or username>")
                    return
                try:
                    # Try resolving as int first, then as entity
                    try:
                        target_id = int(args)
                    except ValueError:
                        target_user = await event.client.get_entity(args)
                        if not isinstance(target_user, PeerUser) and not getattr(target_user, 'user_id', None):
                             await event.reply("Error: Please provide a valid user ID or username.")
                             return
                        target_id = target_user.id if hasattr(target_user, 'id') else target_user.user_id

                    success = await remove_notification_target(target_id)
                    if success:
                        await event.reply(f"OK. Removed notification target: {args}")
                    else:
                        await event.reply(f"Could not remove target {args}. Ensure it exists and is not the owner.")
                except ValueError:
                     await event.reply(f"Error: Could not find user '{args}'.")
                except Exception as e:
                    await event.reply(f"Error removing notification target: {e}")
                return

            elif command == '/notify_list':
                targets = await list_notification_targets()
                if targets:
                    lines = ["Current Notification Targets:"]
                    for target in targets:
                        display = target['first_name'] or target['username'] or f"ID:{target['user_id']}"
                        if target['is_owner']: display += " (Owner)"
                        lines.append(f"- {display} (ID: {target['user_id']})")
                    await event.reply("\n".join(lines))
                else:
                    await event.reply("Error: Could not retrieve notification targets (owner should always be present).")
                return
            # ---------------------------
        # --- End Command Processing ---

        # --- Monitoring Check ---
        should_process = True
        any_monitored = await is_any_chat_monitored()
        # DEBUG LOG
        logger.debug(f"[Msg {message_id}/{chat_id}] is_any_chat_monitored: {any_monitored}")
        if any_monitored:
             is_monitored = await is_chat_monitored(chat_id)
             # DEBUG LOG
             logger.debug(f"[Msg {message_id}/{chat_id}] is_chat_monitored({chat_id}): {is_monitored}")
             if not is_monitored:
                 should_process = False

        if not should_process:
            # DEBUG LOG
            logger.debug(f"[Msg {message_id}/{chat_id}] Skipping processing due to monitor list.")
            return
        # -----------------------

        # --- Prevent self-processing ---
        if _BOT_USER_ID is not None and sender_id == _BOT_USER_ID:
            logger.debug(f"[Msg {message_id}/{chat_id}] Ignoring self-sent message.")
            return

        # --- Regular Message Processing ---
        # DEBUG LOG
        logger.debug(f"[Msg {message_id}/{chat_id}] Passed initial checks, proceeding to log.")

        # 1. Log to Database
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

        # 2. Send Notification to *ALL* targets IF forwarding is active
        if is_forwarding_active and event.client:
            target_ids = await get_all_notification_target_ids()
            if not target_ids:
                 logger.warning(f"[Msg {message_id}/{chat_id}] No notification targets found (owner missing?). Skipping send.")
                 return # Should not happen if owner is always added

            logger.debug(f"[Msg {message_id}/{chat_id}] Checking forwarding: is_forwarding_active={is_forwarding_active}, Targets={target_ids}")

            # Construct the message once
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

            successful_sends = 0
            for target_id in target_ids:
                try:
                    logger.debug(f"[Msg {message_id}/{chat_id}] Attempting notification to target {target_id}.")
                    await event.client.send_message(
                        entity=target_id,
                        message=forward_message,
                        link_preview=False
                    )
                    successful_sends += 1
                except UserIsBlockedError:
                    logger.warning(f"Cannot send notification to {target_id}: User has blocked.")
                except FloodWaitError as e:
                     logger.warning(f"Flood wait sending notification to {target_id}. Waiting {e.seconds}s.")
                     await asyncio.sleep(e.seconds + 1)
                     # Consider retrying send to this user? For now, we skip.
                except Exception as e:
                    logger.error(f"[Msg {message_id}/{chat_id}] Failed to send notification to target {target_id}: {e}")

            if successful_sends > 0:
                 logger.info(f"[Msg {message_id}/{chat_id}] Notification sent to {successful_sends}/{len(target_ids)} targets.")
                 # 4. Mark message as forwarded only if sent to at least one target
                 await mark_message_forwarded(chat_id, message_id)
            else:
                 logger.warning(f"[Msg {message_id}/{chat_id}] Notification failed for all targets.")

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
