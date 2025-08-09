import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime,timezone

def setup_logger(log_name="autoscaler", log_level=logging.INFO, log_format=None):
    """
    Sets up a rotating logger that saves logs to 'logs/' with daily rotation.
    """
    if log_format is None:
        log_format = "%(asctime)s - %(levelname)s - %(message)s"

    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    # File name with timestamp
    log_filename = f"logs/{log_name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"

    # Create handler with daily rotation, keep last 7 logs
    file_handler = TimedRotatingFileHandler(
        filename=log_filename,
        when="midnight",
        interval=1,
        backupCount=2,
        encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    # Configure logger
    logging.basicConfig(level=log_level, handlers=[file_handler, console_handler])