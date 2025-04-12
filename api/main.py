from fastapi import FastAPI
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Assetmatic Micro 1 API",
    description="Basic API endpoints for monitoring the Telegram observer bot.",
    version="0.1.0"
)

@app.get("/health", tags=["General"])
async def health_check():
    """Basic health check endpoint.

    Returns:
        dict: Status indicator.
    """
    logger.debug("Health check endpoint called.")
    return {"status": "ok"}

# Placeholder for future status endpoint
# @app.get("/status", tags=["General"])
# async def get_status():
#     # TODO: Query bot status or DB stats
#     logger.info("Status endpoint called.")
#     return {"bot_name": "Not implemented yet", "logged_messages": -1}