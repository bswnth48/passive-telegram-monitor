from fastapi import FastAPI, Depends
import logging
from typing import Dict, Any # Import Any from typing

# Need access to config and DB stats function
from bot.config import Config, load_config # Assuming we load config here too
from bot.logger import get_db_stats
# Need a way to access the forwarding state - tricky, maybe use a shared state object later?
# For now, we won't include live forwarding status.

logger = logging.getLogger(__name__)

# --- State Management (Simple approach - could be improved) ---
# Load config once when API starts (or use dependency injection)
# This is a simplified approach; a shared state object or dependency
# injection pattern would be better for accessing live bot state.
_api_config: Config = load_config()
# -----------------------------------------------------------

app = FastAPI(
    title="Assetmatic Micro 1 API",
    description="Basic API endpoints for monitoring the Telegram observer bot.",
    version="0.1.0"
)

# Dependency to get config (example)
# async def get_app_config() -> Config:
#    return _api_config

@app.get("/health", tags=["General"])
async def health_check():
    """Basic health check endpoint.

    Returns:
        dict: Status indicator.
    """
    logger.debug("Health check endpoint called.")
    return {"status": "ok"}

@app.get("/status", tags=["General"])
async def get_status() -> Dict[str, Any]:
    """Provides current status information about the bot."""
    logger.info("Status endpoint called.")
    db_stats = await get_db_stats()
    # TODO: Get live forwarding status and group count if possible
    status_info = {
        "bot_name": _api_config.bot_name,
        "api_version": app.version,
        "telegram_login": f"{_api_config.api_id} (User Bot)", # Don't expose full hash
        "monitoring_groups_config": len(_api_config.telegram_groups), # Count from config
        "forwarding_active": "N/A", # Placeholder - requires shared state
        "database_stats": db_stats,
        "ai_model": _api_config.ai_model_name if (_api_config.ai_api_base and _api_config.ai_api_key) else "Disabled",
        "webhook_configured": bool(_api_config.webhook_url)
    }
    return status_info

# Placeholder for future status endpoint
# @app.get("/status", tags=["General"])
# async def get_status():
#     # TODO: Query bot status or DB stats
#     logger.info("Status endpoint called.")
#     return {"bot_name": "Not implemented yet", "logged_messages": -1}