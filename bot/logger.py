import sqlite3
import logging
import os
import aiosqlite
import json # For serializing entities/media info
from datetime import datetime, date, time, timedelta

logger = logging.getLogger(__name__)

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "observations.db")

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
            # TODO: Add ALTER TABLE statements here if we need to update existing tables non-destructively

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

async def get_unforwarded_summary() -> dict:
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

async def get_messages_today() -> list[str]:
    """Retrieves the text content of messages logged today."""
    messages = []
    try:
        today_start = datetime.combine(date.today(), time.min)
        async with aiosqlite.connect(DB_PATH) as db:
            query = """
            SELECT m.text, c.title as chat_title, u.first_name as sender_name
            FROM messages m
            LEFT JOIN chats c ON m.chat_id = c.chat_id
            LEFT JOIN users u ON m.sender_id = u.user_id
            WHERE m.timestamp >= ? AND m.text IS NOT NULL AND LENGTH(m.text) > 0
            ORDER BY m.timestamp ASC;
            """
            async with db.execute(query, (today_start,)) as cursor:
                async for row in cursor:
                    text, chat_title, sender_name = row
                    # Simple formatting for context
                    prefix = f"[{chat_title or 'Unknown Chat'}/{sender_name or 'Unknown Sender'}]: "
                    messages.append(prefix + text)
            logger.info(f"Retrieved {len(messages)} messages from today for summarization.")
    except sqlite3.Error as e:
        logger.error(f"DB error getting today's messages: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error getting today's messages: {e}", exc_info=True)
    return messages

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
