import sqlite3
import logging
import os
import aiosqlite # Use asynchronous version for compatibility with asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "observations.db")

async def initialize_db():
    """Initializes the SQLite database and creates tables if they don't exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON;") # Ensure foreign key constraints are enforced

            # Create chats table (groups/channels/users)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                type TEXT NOT NULL, -- 'group', 'channel', 'user'
                title TEXT, -- Group/Channel title or User's full name
                username TEXT UNIQUE, -- Optional username
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Create users table
            await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                first_name TEXT,
                last_name TEXT,
                is_bot INTEGER NOT NULL, -- 0 for false, 1 for true
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # Create messages table
            await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                sender_id INTEGER, -- Can be null for anonymous channel posts
                timestamp TIMESTAMP NOT NULL,
                text TEXT, -- Message content
                -- Add other relevant fields later (e.g., media type, reply_to)
                PRIMARY KEY (chat_id, message_id),
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
            """)

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
                      sender_is_bot: bool, message_id: int, timestamp: datetime, text: str | None):
    """Logs message details, updating chat and user info if necessary."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON;")

            # Upsert chat info (Insert or ignore if exists)
            await db.execute("""
            INSERT INTO chats (chat_id, type, title, username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO NOTHING;
            """, (chat_id, chat_type, chat_title, chat_username))
            # Consider adding ON CONFLICT DO UPDATE if title/username needs updating

            # Upsert user info (if sender exists)
            if sender_id is not None:
                await db.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, is_bot)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO NOTHING;
                """, (sender_id, sender_username, sender_first_name, sender_last_name, 1 if sender_is_bot else 0))
                # Consider adding ON CONFLICT DO UPDATE for user details

            # Insert message
            await db.execute("""
            INSERT INTO messages (message_id, chat_id, sender_id, timestamp, text)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO NOTHING; -- Avoid duplicates if event fires twice
            """, (message_id, chat_id, sender_id, timestamp, text))

            await db.commit()
            logger.debug(f"Logged message {message_id} from chat {chat_id}")

    except sqlite3.Error as e:
        logger.error(f"Database error logging message {message_id} in chat {chat_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error logging message {message_id} in chat {chat_id}: {e}", exc_info=True)

# Potential future functions:
# async def get_message_count(chat_id: int) -> int:
#     ...
# async def get_user_activity(user_id: int) -> list:
#     ...

# Example test (run directly)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    async def test_logging():
        await initialize_db()
        # Example 1: Group message
        await log_message(
            chat_id=-100123456, chat_type='group', chat_title='Test Group', chat_username='testgroup',
            sender_id=98765, sender_username='testuser', sender_first_name='Test', sender_last_name='User',
            sender_is_bot=False, message_id=101, timestamp=datetime.now(), text='Hello from group!'
        )
        # Example 2: Channel post (no sender)
        await log_message(
            chat_id=-100987654, chat_type='channel', chat_title='Test Channel', chat_username='testchannel',
            sender_id=None, sender_username=None, sender_first_name=None, sender_last_name=None,
            sender_is_bot=False, message_id=202, timestamp=datetime.now(), text='Channel announcement!'
        )
        # Example 3: DM from user
        await log_message(
            chat_id=12345, chat_type='user', chat_title='Another User', chat_username='anotheruser',
            sender_id=12345, sender_username='anotheruser', sender_first_name='Another', sender_last_name='User',
            sender_is_bot=False, message_id=303, timestamp=datetime.now(), text='Direct message'
        )

        # Verify data (optional)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM messages") as cursor:
                count = await cursor.fetchone()
                logger.info(f"Total messages in DB: {count[0]}")
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                count = await cursor.fetchone()
                logger.info(f"Total users in DB: {count[0]}")
            async with db.execute("SELECT COUNT(*) FROM chats") as cursor:
                count = await cursor.fetchone()
                logger.info(f"Total chats in DB: {count[0]}")

    asyncio.run(test_logging())
