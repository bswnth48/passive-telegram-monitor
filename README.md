# Assetmatic Micro 1: Passive Telegram Observation Bot

A modular Python project that creates a passive Telegram bot capable of observing message flow, logging details (including links/media info), and interacting via commands. It includes a basic API for health checks.

## Features

- Passive observation of Telegram groups/chats.
- Logs message details (text, sender, chat, timestamp, entities, media info) to SQLite.
- Forwards customizable notifications for observed messages to a target user.
- Control notification forwarding via Telegram commands (`/start_forwarding`, `/stop_forwarding`).
- Provides AI-powered summaries of today's messages via `/summary_today` command (requires AI API configuration).
- Basic FastAPI API server with a `/health` endpoint.
- Supports joining configured public Telegram groups.
- Modular design.
- Docker and GitHub Codespaces compatible.

## Setup and Installation

1.  **Clone the Repository:**
    ```bash
    git clone <repository-url>
    cd assetmatic-micro-1
    ```

2.  **Create and Activate Conda Environment (Recommended):**

    As per project requirements, Python dependencies must be managed within a Conda environment.

    ```bash
    # Create a new environment (e.g., named 'assetmatic_env') with Python 3.10+
    conda create -n assetmatic_env python=3.10 -y

    # Activate the environment
    conda activate assetmatic_env
    ```
    *You must have this environment active for the following steps and whenever running the bot.*

3.  **Install Dependencies:**

    Ensure your Conda environment is active before running:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Create and Configure `.env` file:**

    Create a `.env` file in the project root (you can copy `.env.example` if it exists). Fill it with:

    ```dotenv
    # Telegram API Credentials (REQUIRED - Obtain from https://my.telegram.org/apps)
    API_ID=12345678
    API_HASH=your_api_hash_string_here

    # Bot Configuration
    BOT_NAME=MyTelegramBot # Name for the bot instance and session file
    WEBHOOK_URL=http://example.com/webhook # REQUIRED (placeholder OK for now)
    WEBHOOK_INTERVAL_MINUTES=60 # Optional: Planned for webhook feature
    TELEGRAM_GROUPS=https://t.me/some_public_group # Optional: Comma-separated public group links to join

    # --- AI Configuration (OPTIONAL - Needed for /summary_today) ---
    # Use an OpenAI-compatible endpoint (e.g., for Gemini)
    AI_API_BASE=https://your-ai-endpoint.com/v1 # Base URL of the AI service
    AI_API_KEY=YOUR_AI_API_KEY_HERE          # Your API Key for the AI service
    AI_MODEL_NAME=gemini-pro              # Model name to use for summarization
    ```
    *(See Configuration Options section below for details)*

5.  **Initial Database Setup:**
    The first time you run the bot, it will create the SQLite database file in the `data/` directory. If you encounter schema errors after code updates, delete `data/observations.db` and let the bot recreate it on the next run.

## Running the Bot

Ensure your Conda environment is active (`conda activate assetmatic_env`).

```bash
python main.py
```
*   **First Run:** Authorize the session by entering your phone number, login code, and potentially 2FA password when prompted.
*   **API:** The FastAPI server will also start (usually on `http://localhost:8000`). Check `/health` for status.
*   **Stopping:** Press `Ctrl+C`.

## Interacting with the Bot (Commands)

Send these commands from the **Owner** Telegram account (whose API credentials are used):

**Notification Control:**
*   `/stop_forwarding`: Pauses sending notifications for new messages to all targets.
*   `/start_forwarding`: Resumes notifications (shows summary of missed).

**Notification Targets:**
*   `/notify_add <user_id or username>`: Add another user to receive notifications/summaries.
*   `/notify_remove <user_id or username>`: Stop sending notifications/summaries to this user (cannot remove owner).
*   `/notify_list`: Show all users currently receiving notifications/summaries.

**Monitoring Scope:**
*   `/monitor_add <chat_id or username/link>`: Add a specific chat to the monitor list. Once the list is populated, only messages from these chats will be processed.
*   `/monitor_remove <chat_id or username/link>`: Remove a chat from the monitor list.
*   `/monitor_list`: Show the list of currently monitored chats.
*   `/monitor_clear`: Clears the entire monitor list, reverting to processing messages from all chats.

**Summarization:**
*   `/summary_today`: Requests an AI-generated summary of messages logged today (requires AI env vars to be set).

**Help:**
*   `/help`: Shows this help message.

## Running with Docker

Or with Docker:

```