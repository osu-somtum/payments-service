"""Async MySQL connection — mirrors bancho.py's databases[] pattern."""
from __future__ import annotations

import databases

from app import settings

database: databases.Database = databases.Database(settings.DB_DSN)
