# Assetmatic Micro 1: Passive Telegram Observation Bot

A modular Python project that creates a passive Telegram bot capable of observing message flow in public groups, logging metadata, and triggering webhooks based on configurable events.

## Features

- Passive observation of Telegram groups
- Message and metadata logging to SQLite
- Webhook triggers based on configurable rules
- Modular design with FastAPI backend
- Docker and GitHub Codespaces compatible

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

    Copy the `.env.example` file (if provided) or create a new file named `.env` in the project root.
    Fill it with your Telegram API credentials and desired configuration:

    ```dotenv
    # Telegram API Credentials (REQUIRED - Obtain from https://my.telegram.org/apps)
    API_ID=12345678
    API_HASH=your_api_hash_string_here

    # Bot Configuration
    BOT_NAME=MyTelegramBot # Name for the bot instance and session file
    WEBHOOK_URL=http://example.com/webhook # REQUIRED (even if webhook logic is not fully used yet)
    WEBHOOK_INTERVAL_MINUTES=60 # Optional: How often to ping (default 60)
    TELEGRAM_GROUPS=https://t.me/some_public_group,https://t.me/another_public_group # Optional: Comma-separated public group links
    ```
    *(See Configuration Options section below for details)*

## Running the Bot

Ensure your Conda environment is active (`conda activate assetmatic_env`).

```bash
python main.py
```

*   **First Run:** You will likely be prompted in the terminal to enter your phone number, the code sent to your Telegram app, and potentially your 2FA password to authorize the session.
*   **Subsequent Runs:** The bot should log in automatically using the saved session file (e.g., `sessions/mytelegrambot_session`).

To stop the bot, press `Ctrl+C` in the terminal.

## Running with Docker

Or with Docker:

```bash
docker build -t assetmatic-micro-1 .
docker run -d --name assetmatic-bot --env-file .env assetmatic-micro-1
```

## Project Structure

```
assetmatic-micro-1/
├── bot/             # Telegram bot logic
│   ├── config.py    # Configuration loading
│   ├── observer.py  # Telegram message observer
│   └── logger.py    # Data logging
├── api/             # FastAPI endpoints
│   └── routes.py    # API routes
├── scribe/          # Codegen integration
│   └── plugin.py
├── main.py          # Entry point
├── Dockerfile       # Docker configuration
└── requirements.txt # Dependencies
```

## Configuration Options

Configuration is loaded from the `.env` file:

*   `API_ID`: Your numeric Telegram API ID (**Required**).
*   `API_HASH`: Your alphanumeric Telegram API Hash (**Required**).
*   `BOT_NAME`: Name for this bot instance and its session file (Default: `DefaultBotName`).
*   `WEBHOOK_URL`: The URL the bot should eventually ping (**Required** by the current config loader).
*   `WEBHOOK_INTERVAL_MINUTES`: How often, in minutes, the webhook should be triggered (Default: `60`). Must be a positive integer.
*   `TELEGRAM_GROUPS`: A comma-separated list of public Telegram group URLs the bot should monitor (Optional. If empty, the bot only monitors existing chats/DMs).

## Development

This project is configured for GitHub Codespaces. Opening it in Codespaces will automatically set up the development environment.

For local development:

1.  Clone the repository.
2.  Follow the Setup and Installation steps (including Conda environment and `.env` file).
3.  Activate the Conda environment (`conda activate assetmatic_env`).
4.  Run the bot: `python main.py`

## License

Proprietary - Assetmatic Internal Use Only
