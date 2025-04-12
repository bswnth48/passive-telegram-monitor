import sqlite3
import logging
import os
import aiosqlite
import json # For serializing entities/media info
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Tuple, Any # Added Any

logger = logging.getLogger(__name__)

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "observations.db")
OWNER_USER_ID = 1137119534 # Define owner ID globally here

async def initialize_db():
    """Initializes the SQLite database and creates/updates tables."""
    # NOTE: If schema changes significantly, deleting the existing DB file might be needed.
    os.makedirs(DB_DIR, exist_ok=True)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON;")

            # Create chats table (if not exists)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT,
                username TEXT UNIQUE,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Create users table (if not exists)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                first_name TEXT,
                last_name TEXT,
                is_bot INTEGER NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Create messages table (if not exists)
            # Added entities, media_type, media_info, forwarded_to_user
            await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                sender_id INTEGER,
                timestamp TIMESTAMP NOT NULL,
                text TEXT, -- Nullable now
                entities TEXT, -- JSON formatted list of entities
                media_type TEXT, -- e.g., 'photo', 'video', 'document'
                media_info TEXT, -- JSON formatted media details
                forwarded_to_user INTEGER DEFAULT 0 NOT NULL, -- 0=No, 1=Yes
                PRIMARY KEY (chat_id, message_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
            """)

            # --- New Table: Monitored Chats ---
            await db.execute("""
            CREATE TABLE IF NOT EXISTS monitored_chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,          -- Store for easier listing
                username TEXT,       -- Store for easier listing
                added_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            # --------------------------------

            # --- New Table: Notification Targets ---
            await db.execute("""
            CREATE TABLE IF NOT EXISTS notification_targets (
                target_user_id INTEGER PRIMARY KEY,
                username TEXT,       -- Store for easier listing
                first_name TEXT,     -- Store for easier listing
                is_owner INTEGER DEFAULT 0 NOT NULL, -- 1 for the owner
                added_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            # Ensure the owner is always present
            await db.execute("""
            INSERT INTO notification_targets (target_user_id, is_owner, first_name)
            VALUES (?, 1, 'Owner')
            ON CONFLICT(target_user_id) DO UPDATE SET is_owner=excluded.is_owner;
            """, (OWNER_USER_ID,))
            # ---------------------------------------

            await db.commit()
            logger.info(f"Database initialized successfully at {DB_PATH}")

    except sqlite3.Error as e:
        logger.error(f"Database error during initialization: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred during DB initialization: {e}", exc_info=True)
        raise

async def log_message(chat_id: int, chat_type: str, chat_title: str | None,
                      chat_username: str | None, sender_id: int | None, sender_username: str | None,
                      sender_first_name: str | None, sender_last_name: str | None,
                      sender_is_bot: bool, message_id: int, timestamp: datetime, text: str | None,
                      entities: list | None, media_type: str | None, media_info: dict | None):
    """Logs message details, including entities and media info, updating chat/user info."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON;")

            # Upsert chat info
            await db.execute("""
            INSERT INTO chats (chat_id, type, title, username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO NOTHING;
            """, (chat_id, chat_type, chat_title, chat_username))

            # Upsert user info
            if sender_id is not None:
                await db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, is_bot)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO NOTHING;
                """, (sender_id, sender_username, sender_first_name, sender_last_name, 1 if sender_is_bot else 0))

            # Serialize complex data to JSON
            entities_json = json.dumps(entities) if entities else None
            media_info_json = json.dumps(media_info) if media_info else None

            # Insert message, forwarded_to_user defaults to 0
            await db.execute("""
            INSERT INTO messages (message_id, chat_id, sender_id, timestamp, text, entities, media_type, media_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO NOTHING;
            """, (message_id, chat_id, sender_id, timestamp, text, entities_json, media_type, media_info_json))

            await db.commit()
            logger.debug(f"Logged message {message_id} from chat {chat_id} (Media: {media_type or 'None'})")

    except sqlite3.Error as e:
        logger.error(f"Database error logging message {message_id} in chat {chat_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error logging message {message_id} in chat {chat_id}: {e}", exc_info=True)

async def mark_message_forwarded(chat_id: int, message_id: int):
    """Marks a specific message as forwarded in the database."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
            UPDATE messages
            SET forwarded_to_user = 1
            WHERE chat_id = ? AND message_id = ? AND forwarded_to_user = 0
            """, (chat_id, message_id))
            await db.commit()
            logger.debug(f"Marked message {message_id} in chat {chat_id} as forwarded.")
    except sqlite3.Error as e:
        logger.error(f"DB error marking message {message_id}/{chat_id} forwarded: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error marking message {message_id}/{chat_id} forwarded: {e}", exc_info=True)

async def get_unforwarded_summary() -> Dict[str, int]:
    """Gets a summary of unforwarded messages (e.g., count per chat)."""
    summary = {}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            query = """
            SELECT c.title, c.username, c.chat_id, COUNT(m.message_id) as unforwarded_count
            FROM messages m
            JOIN chats c ON m.chat_id = c.chat_id
            WHERE m.forwarded_to_user = 0
            GROUP BY m.chat_id
            ORDER BY unforwarded_count DESC;
            """
            async with db.execute(query) as cursor:
                async for row in cursor:
                    title, username, chat_id, count = row
                    chat_display = title or username or f"ID:{chat_id}"
                    summary[chat_display] = count
            logger.info(f"Generated summary for {len(summary)} chats with unforwarded messages.")
    except sqlite3.Error as e:
        logger.error(f"DB error getting unforwarded summary: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error getting unforwarded summary: {e}", exc_info=True)
    return summary

async def get_messages_since(timestamp: datetime) -> List[Dict[str, Any]]:
    """Retrieves message details logged since the given timestamp."""
    messages = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Select relevant fields for summarization context
            query = """
            SELECT m.timestamp, m.text, m.entities, m.media_type,
                   c.title as chat_title, c.type as chat_type,
                   u.first_name as sender_name, u.is_bot as sender_is_bot
            FROM messages m
            LEFT JOIN chats c ON m.chat_id = c.chat_id
            LEFT JOIN users u ON m.sender_id = u.user_id
            WHERE m.timestamp > ? -- Fetch messages *after* the last check
            ORDER BY m.timestamp ASC;
            """
            async with db.execute(query, (timestamp,)) as cursor:
                async for row in cursor:
                    # Construct a dictionary for each message
                    msg_data = {
                        "timestamp": row[0],
                        "text": row[1],
                        "entities": json.loads(row[2]) if row[2] else None,
                        "media_type": row[3],
                        "chat_title": row[4],
                        "chat_type": row[5],
                        "sender_name": row[6],
                        "sender_is_bot": bool(row[7])
                    }
                    messages.append(msg_data)
            logger.info(f"Retrieved {len(messages)} messages since {timestamp} for summarization.")
    except sqlite3.Error as e:
        logger.error(f"DB error getting messages since {timestamp}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error getting messages since {timestamp}: {e}", exc_info=True)
    return messages

async def get_db_stats() -> Dict[str, int]:
    """Retrieves basic statistics from the database."""
    stats = {
        "total_messages": 0,
        "total_chats": 0,
        "total_users": 0
    }
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM messages") as cursor:
                result = await cursor.fetchone()
                if result: stats["total_messages"] = result[0]
            async with db.execute("SELECT COUNT(*) FROM chats") as cursor:
                result = await cursor.fetchone()
                if result: stats["total_chats"] = result[0]
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                result = await cursor.fetchone()
                if result: stats["total_users"] = result[0]
            logger.debug(f"Retrieved DB stats: {stats}")
    except sqlite3.Error as e:
        logger.error(f"DB error getting stats: {e}", exc_info=True)
        # Return default stats on error
    except Exception as e:
        logger.error(f"Unexpected error getting stats: {e}", exc_info=True)
        # Return default stats on error
    return stats

# --- Monitored Chat Functions ---

async def add_monitored_chat(chat_id: int, title: str | None, username: str | None):
    """Adds a chat to the monitored list."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
            INSERT INTO monitored_chats (chat_id, title, username)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, username=excluded.username;
            """, (chat_id, title, username))
            await db.commit()
            logger.info(f"Added/Updated monitored chat: ID={chat_id}, Title={title}, Username={username}")
    except Exception as e:
        logger.error(f"Error adding monitored chat {chat_id}: {e}", exc_info=True)

async def remove_monitored_chat(chat_id: int):
    """Removes a chat from the monitored list."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("DELETE FROM monitored_chats WHERE chat_id = ?", (chat_id,))
            await db.commit()
            if cursor.rowcount > 0:
                logger.info(f"Removed monitored chat: ID={chat_id}")
                return True
            else:
                logger.warning(f"Attempted to remove non-monitored chat: ID={chat_id}")
                return False
    except Exception as e:
        logger.error(f"Error removing monitored chat {chat_id}: {e}", exc_info=True)
        return False

async def list_monitored_chats() -> List[Dict[str, Any]]:
    """Lists all currently monitored chats."""
    chats = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            query = "SELECT chat_id, title, username, added_timestamp FROM monitored_chats ORDER BY added_timestamp DESC"
            async with db.execute(query) as cursor:
                async for row in cursor:
                    chats.append({
                        "chat_id": row[0],
                        "title": row[1],
                        "username": row[2],
                        "added_timestamp": row[3]
                    })
    except Exception as e:
        logger.error(f"Error listing monitored chats: {e}", exc_info=True)
    return chats

async def is_chat_monitored(chat_id: int) -> bool:
    """Checks if a specific chat ID is in the monitored list."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM monitored_chats WHERE chat_id = ? LIMIT 1", (chat_id,)) as cursor:
                result = await cursor.fetchone()
                return bool(result)
    except Exception as e:
        logger.error(f"Error checking if chat {chat_id} is monitored: {e}", exc_info=True)
        return False # Default to false on error

async def is_any_chat_monitored() -> bool:
    """Checks if the monitored list is currently populated."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM monitored_chats LIMIT 1") as cursor:
                result = await cursor.fetchone()
                return bool(result)
    except Exception as e:
        logger.error(f"Error checking if any chat is monitored: {e}", exc_info=True)
        return False # Default to false (effectively monitor all) on error

async def clear_monitored_chats():
    """Removes all entries from the monitored chats list."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("DELETE FROM monitored_chats")
            await db.commit()
            deleted_count = cursor.rowcount
            logger.info(f"Cleared {deleted_count} entries from monitored_chats table.")
            return deleted_count
    except Exception as e:
        logger.error(f"Error clearing monitored chats: {e}", exc_info=True)
        return -1 # Indicate error

# --- Notification Target Functions ---

async def add_notification_target(user_id: int, username: str | None, first_name: str | None) -> bool:
    """Adds a user to the notification target list. Returns False if trying to add owner again."""
    if user_id == OWNER_USER_ID:
        logger.warning("Attempted to re-add owner ID as notification target. Ignoring.")
        return False # Owner is always implicitly a target
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
            INSERT INTO notification_targets (target_user_id, username, first_name, is_owner)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(target_user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name;
            """, (user_id, username, first_name))
            await db.commit()
            logger.info(f"Added/Updated notification target: ID={user_id}, Name={first_name}, Username={username}")
            return True
    except Exception as e:
        logger.error(f"Error adding notification target {user_id}: {e}", exc_info=True)
        return False

async def remove_notification_target(user_id: int) -> bool:
    """Removes a user from the notification target list. Protects the owner."""
    if user_id == OWNER_USER_ID:
        logger.warning("Attempted to remove owner ID from notification targets. Operation denied.")
        return False # Cannot remove owner
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("DELETE FROM notification_targets WHERE target_user_id = ? AND is_owner = 0", (user_id,))
            await db.commit()
            if cursor.rowcount > 0:
                logger.info(f"Removed notification target: ID={user_id}")
                return True
            else:
                logger.warning(f"Attempted to remove non-existent or owner target: ID={user_id}")
                return False
    except Exception as e:
        logger.error(f"Error removing notification target {user_id}: {e}", exc_info=True)
        return False

async def list_notification_targets() -> List[Dict[str, Any]]:
    """Lists all currently configured notification targets."""
    targets = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            query = "SELECT target_user_id, username, first_name, is_owner, added_timestamp FROM notification_targets ORDER BY added_timestamp DESC"
            async with db.execute(query) as cursor:
                async for row in cursor:
                    targets.append({
                        "user_id": row[0],
                        "username": row[1],
                        "first_name": row[2],
                        "is_owner": bool(row[3]),
                        "added_timestamp": row[4]
                    })
    except Exception as e:
        logger.error(f"Error listing notification targets: {e}", exc_info=True)
    return targets

async def get_all_notification_target_ids() -> List[int]:
    """Gets a list of all target user IDs (including the owner)."""
    ids = []
    try:
        async with aiosqlite.connect(DB_PATH) as db:
             # Owner is always implicitly included via the initial insert
            query = "SELECT target_user_id FROM notification_targets"
            async with db.execute(query) as cursor:
                async for row in cursor:
                    ids.append(row[0])
    except Exception as e:
        logger.error(f"Error getting all notification target IDs: {e}", exc_info=True)
    # Ensure owner is always included, even if DB read fails somehow
    if OWNER_USER_ID not in ids:
        ids.append(OWNER_USER_ID)
    return list(set(ids)) # Return unique list

# -------------------------------

# Example test remains largely the same but needs updates if testing new fields
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    import asyncio # Ensure asyncio is imported for test

    async def test_logging():
        await initialize_db()
        # Example 1: Group message with a link (mock entity)
        mock_entities = [{'type': 'url', 'offset': 11, 'length': 11}]
        await log_message(
            chat_id=-100123456, chat_type='group', chat_title='Test Group', chat_username='testgroup',
            sender_id=98765, sender_username='testuser', sender_first_name='Test', sender_last_name='User',
            sender_is_bot=False, message_id=101, timestamp=datetime.now(), text='Hello from group! http://example.com',
            entities=mock_entities, media_type=None, media_info=None
        )
        # Example 2: Message with media (mock photo)
        mock_media_info = {'id': 1234567890, 'access_hash': 9876543210, 'caption': 'Test Photo'}
        await log_message(
            chat_id=-100987654, chat_type='channel', chat_title='Test Channel', chat_username='testchannel',
            sender_id=None, sender_username=None, sender_first_name=None, sender_last_name=None,
            sender_is_bot=False, message_id=202, timestamp=datetime.now(), text='Test Photo', # Text might be caption
            entities=None, media_type='photo', media_info=mock_media_info
        )
        # Example 3: Plain DM
        await log_message(
            chat_id=12345, chat_type='user', chat_title='Another User', chat_username='anotheruser',
            sender_id=12345, sender_username='anotheruser', sender_first_name='Another', sender_last_name='User',
            sender_is_bot=False, message_id=303, timestamp=datetime.now(), text='Direct message',
            entities=None, media_type=None, media_info=None
        )

        # Verify counts
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM messages") as cursor:
                count = await cursor.fetchone()
                logger.info(f"Total messages in DB: {count[0]}")
            # Add verification for new columns if needed
            # async with db.execute("SELECT text, entities, media_type, media_info FROM messages LIMIT 1") as cursor:
            #     row = await cursor.fetchone()
            #     logger.info(f"Sample row: {row}")

    asyncio.run(test_logging())
