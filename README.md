# Assetmatic Micro 1: Passive Telegram Observation Bot

A modular Python project that creates a passive Telegram bot using a user account. It observes message flow, logs details (including links/media info) to SQLite, and allows for dynamic control via Telegram commands.

## Features

-   **Passive Observation:** Monitors messages in specified Telegram groups/chats or all chats the user account is in.
-   **Detailed Logging:** Saves message details (text, sender, chat, timestamp, entities, media info) to a local SQLite database (`data/observations.db`).
-   **Dynamic Chat Monitoring:** Control which specific chats are monitored using owner commands (`/monitor_add`, `/monitor_remove`, `/monitor_list`, `/monitor_clear`). Monitors all chats by default if no specific chats are added.
-   **Multi-Target Notifications:** Forwards customizable notifications for observed messages to one or more configured Telegram users (managed via owner commands).
-   **Notification Control:** Pause/resume notifications (`/stop_forwarding`, `/start_forwarding`) and manage recipients (`/notify_add`, `/notify_remove`, `/notify_list`) via owner commands.
-   **Scheduled AI Summaries:** Periodically generates an AI summary of recent messages and sends it to all configured notification targets (requires AI API configuration in `.env`).
-   **On-Demand AI Summaries:** Request an AI summary for the current day via the owner command `/summary_today`.
-   **Scheduled Webhook:** Sends batches of raw message data (logged since the last send) to an external webhook URL at a configured interval (requires `WEBHOOK_URL` and `WEBHOOK_INTERVAL_MINUTES` in `.env`).
-   **API Monitoring:** Includes a basic FastAPI server with `/health` and `/status` endpoints for monitoring.
-   **Automatic Group Joining:** Attempts to join public groups/channels listed in the `TELEGRAM_GROUPS` configuration.
-   **Modular Design:** Separated components for bot logic, API, database, AI, etc.
-   **Deployment Ready:** Includes a `Dockerfile` for containerization and GitHub Codespaces configuration.

## Setup and Installation

Choose **one** of the following methods:

### Method 1: Running Natively (Recommended for Development)

1.  **Clone the Repository:**
    ```bash
    git clone <repository-url> # Replace with your repo URL
    cd assetmatic-micro-1
    ```

2.  **Create and Activate Conda Environment:**
    > ℹ️ **Note:** Using Conda is recommended to maintain project-specific dependencies.

    ```bash
    # Create a new environment (e.g., named 'assetmatic_env') with Python 3.10+
    conda create -n assetmatic_env python=3.10 -y

    # Activate the environment
    conda activate assetmatic_env
    ```
    *You must have this environment active for the following steps and whenever running the bot natively.*

3.  **Install Dependencies:**
    Ensure your Conda environment is active before running:
```bash
pip install -r requirements.txt
```

4.  **Create and Configure `.env` file:**
    See the **[Configuration](#configuration)** section below for details on creating and populating the `.env` file. **Minimum required:** `API_ID`, `API_HASH`.

5.  **Initial Database Setup:**
    The first time you run the bot, it will create the SQLite database file (`data/observations.db`) and the session file (`sessions/<BOT_NAME>_session.session`). If you encounter schema errors after code updates, consider deleting `data/observations.db` and letting the bot recreate it on the next run (this will delete logged data).

6.  **Run the Bot:**
    Ensure your Conda environment is active (`conda activate assetmatic_env`).
```bash
python main.py
```
    *   **First Run:** Authorize the session by entering your phone number, login code, and potentially 2FA password when prompted in the terminal.
    *   **API:** The FastAPI server will also start (usually on `http://localhost:8000`). Check `/health` for status.
    *   **Stopping:** Press `Ctrl+C` in the terminal.

### Method 2: Running with Docker

1.  **Clone the Repository:**
    ```bash
    git clone <repository-url> # Replace with your repo URL
    cd assetmatic-micro-1
    ```

2.  **Create and Configure `.env` file:**
    See the **[Configuration](#configuration)** section below. The `.env` file is required *before* building the image if you want to include credentials directly (not recommended for production) or it must be mounted as a volume.

3.  **Build the Docker Image:**
```bash
docker build -t assetmatic-micro-1 .
    ```

4.  **Run the Docker Container:**
    > 🚨 **Warning:** You need to manage the `.env` file, session data, and the database data persistently using Docker volumes.

    ```bash
    docker run -d --name assetmatic-bot \\
      -p 8000:8000 \\
      --env-file .env \\
      -v $(pwd)/sessions:/app/sessions \\
      -v $(pwd)/data:/app/data \\
      assetmatic-micro-1
    ```
    *   `-d`: Run in detached mode (background).
    *   `--name assetmatic-bot`: Assign a name to the container.
    *   `-p 8000:8000`: Map port 8000 on your host to port 8000 in the container (for FastAPI).
    *   `--env-file .env`: Load environment variables from your `.env` file.
    *   `-v $(pwd)/sessions:/app/sessions`: Mount the local `sessions` directory into the container to persist the Telegram session file. **Crucial for avoiding re-login.**
    *   `-v $(pwd)/data:/app/data`: Mount the local `data` directory into the container to persist the SQLite database. **Crucial for keeping logs.**
    *   `assetmatic-micro-1`: The name of the image you built.

    *   **First Run (Docker):** You will need to run the container *interactively* the very first time to handle the Telegram login prompt:
        ```bash
        # Stop the detached container if it's running from the command above
        docker stop assetmatic-bot
        docker rm assetmatic-bot

        # Run interactively for login
        docker run -it --rm --name assetmatic-bot-login \\
          -p 8000:8000 \\
          --env-file .env \\
          -v $(pwd)/sessions:/app/sessions \\
          -v $(pwd)/data:/app/data \\
          assetmatic-micro-1

        # Follow the login prompts (phone, code, 2FA). Once logged in, stop with Ctrl+C.
        # Now you can run the detached container again using the first `docker run` command.
        ```

    *   **Viewing Logs (Docker):** `docker logs assetmatic-bot`
    *   **Stopping (Docker):** `docker stop assetmatic-bot`
    *   **Removing (Docker):** `docker rm assetmatic-bot` (after stopping)


## Configuration

Create a `.env` file in the project root directory. Copy the example below and fill in your values.

```dotenv
# .env Example

# --- Telegram API Credentials (REQUIRED) ---
# Get from https://my.telegram.org/apps
API_ID=12345678
API_HASH=your_api_hash_string_here

# --- Bot Configuration (REQUIRED) ---
# Used for naming the session file (e.g., sessions/myobserverbot_session.session)
BOT_NAME=MyObserverBot

# --- Telegram Groups to Join (Optional) ---
# Comma-separated public group links/usernames the bot should attempt to join on startup.
# Example: TELEGRAM_GROUPS=https://t.me/some_public_group,@another_group,https://t.me/joinchat/ABCDEFG
# Leave empty or comment out if you don't want the bot to auto-join groups.
TELEGRAM_GROUPS=

# --- Scheduled Tasks Interval (REQUIRED if using AI Summaries or Webhook) ---
# Controls how often the AI summary is generated/sent AND the webhook is triggered (in minutes).
# Set to 0 or comment out to disable scheduled tasks.
WEBHOOK_INTERVAL_MINUTES=30 # Default: 30 if not set, but > 0 required for tasks

# --- External Webhook (Optional) ---
# If set, sends raw message batches to this URL periodically based on the interval above.
# WEBHOOK_URL=https://your-webhook-endpoint.com/data

# --- Primary AI Configuration (Optional) ---
# Used for summaries and NLP queries. If this fails or is missing, OpenRouter is used as fallback.
# Requires an OpenAI-compatible API endpoint.
AI_API_BASE=https://api.openai.com/v1
AI_API_KEY=sk-YourApiKeyHere
AI_MODEL_NAME=gpt-3.5-turbo # Or specify another model like 'mistralai/Mixtral-8x7B-Instruct-v0.1'

# --- OpenRouter Fallback Configuration (Optional) ---
# Used if the primary AI fails or is not configured. Get key from https://openrouter.ai/
OPENROUTER_API_KEY=sk-or-v1-abc...xyz
# Specify the model to use for fallback (see OpenRouter docs for options)
OPENROUTER_FALLBACK_MODEL=qwen/qwen2.5-vl-3b-instruct:free
```

**Configuration Variables:**

| Variable                    | Required?                           | Description                                                                                                 | Default                             |
| :-------------------------- | :---------------------------------- | :---------------------------------------------------------------------------------------------------------- | :---------------------------------- |
| `API_ID`                    | **Yes**                             | Your Telegram API ID.                                                                                       | -                                   |
| `API_HASH`                  | **Yes**                             | Your Telegram API Hash.                                                                                     | -                                   |
| `BOT_NAME`                  | **Yes**                             | Name for the bot instance and its session file.                                                             | `DefaultBotName`                    |
| `TELEGRAM_GROUPS`           | No                                  | Comma-separated list of public group URLs or usernames to join.                                             | Empty                               |
| `WEBHOOK_INTERVAL_MINUTES` | Yes (for Summary/Webhook)           | Interval in minutes for scheduled AI summary and webhook tasks. Must be > 0 if using either feature.        | 30                                  |
| `WEBHOOK_URL`               | No                                  | URL to send periodic raw message batches to. Enables webhook feature.                                       | None                                |
| `AI_API_BASE`               | No (Uses OpenRouter if missing)     | Base URL of the primary OpenAI-compatible API endpoint.                                                     | None                                |
| `AI_API_KEY`                | No (Uses OpenRouter if missing)     | API key for the primary AI service.                                                                         | None                                |
| `AI_MODEL_NAME`             | No (Uses Primary AI default)        | Name/Identifier of the primary language model for summaries/queries.                                        | `gemini-pro`                        |
| `OPENROUTER_API_KEY`        | No (Fallback disabled if missing) | API key for OpenRouter.ai, used as fallback.                                                              | None                                |
| `OPENROUTER_FALLBACK_MODEL` | No                                  | Model identifier for OpenRouter fallback (e.g., from OpenRouter docs).                                      | `qwen/qwen2.5-vl-3b-instruct:free` |


## Interacting with the Bot (Owner Commands)

Send these commands from the **Owner** account (the account associated with the `API_ID`/`API_HASH`) directly to the bot (e.g., in your "Saved Messages" chat):

**Notification Control:**
*   `/stop_forwarding`: Pauses sending notifications for new messages to all targets.
*   `/start_forwarding`: Resumes notifications (shows summary of missed messages).

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

## API Endpoints

When running, the FastAPI server is available (default: `http://localhost:8000` or the mapped Docker port):

*   `GET /health`: Returns `{"status": "ok"}` if the API server is running.
*   `GET /status`: Returns a JSON object with current bot status, DB stats, and configuration info.

## Project Structure

```mermaid
---
title: Assetmatic Micro 1 - Simplified Architecture
---
flowchart TD
    subgraph Host System
        DOCKER[Docker Container (Optional)]
    end

    subgraph DOCKER[" "]
        A[main.py Entrypoint]
        subgraph "Async Tasks"
            B{"Bot Runner Task"}
            C{"API Server Task (FastAPI)"}
            E{"Periodic Scheduler"}
        end
    end

    subgraph "Bot Components"
        F[bot/observer.py Handler]
        G[bot/logger.py DB Interface]
        K[bot/summarizer.py AI Interface]
        L[bot/webhook.py Sender]
        Q[bot/config.py Loader]
    end

    subgraph "API Components"
        P[api/main.py Routes]
    end

    subgraph "External Services / Data"
        D([Telegram API])
        M[(data/observations.db SQLite)]
        N({AI API Endpoint})
        O({External Webhook URL})
        SESSIONS([sessions/...session File])
    end

    A --> B
    A --> C
    B --> D
    B --> E
    B --> SESSIONS
    C --> P

    E --> K
    E --> L
    E --> G # Scheduler fetches messages
    E --> H # Scheduler sends summary to targets

    F --> D # Observer interacts with Telegram
    F --> G # Observer logs messages
    F --> H[Notification Targets via Logger] # Observer sends notifications
    F --> I[Monitored Chats via Logger] # Observer checks monitor list
    F -- processes --> J((Messages))

    P --> G # API gets DB stats
    P --> Q # API gets Config

    K --> N # Summarizer calls AI API
    L --> O # Webhook sender calls URL
    G --> M # Logger writes/reads DB
    Q --> ".env File"

    style M fill:#lightgrey,stroke:#333,stroke-width:2px
    style N fill:#lightblue,stroke:#333,stroke-width:2px
    style O fill:#lightblue,stroke:#333,stroke-width:2px
    style SESSIONS fill:#lightgrey,stroke:#333,stroke-width:2px
```
*(Simplified component view)*

## Development

*   **Environment:** Recommended setup uses Conda for managing Python dependencies locally (see Setup). GitHub Codespaces is also configured for a cloud-based environment.
*   **Branching:** Use standard Git flow (e.g., feature branches, pull requests).
*   **Testing:** (Add details here if tests are implemented later).

## License

(Specify License - e.g., MIT License)

Copyright (c) 2025 Assetmatic / Approgramme