"""
PostgreSQL Database Connection
Async connection pools for Primary (chat) and CRM (products/company) using a single accessor.
"""

import asyncpg
import os
from typing import Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

# Database configuration (Primary - chatbot)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "minaai_chatbot")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# CRM Database configuration (Products/Company info)
CRM_DB_HOST = os.getenv("CRM_DB_HOST", DB_HOST)
CRM_DB_PORT = int(os.getenv("CRM_DB_PORT", str(DB_PORT)))
CRM_DB_NAME = os.getenv("CRM_DB_NAME", DB_NAME)
CRM_DB_USER = os.getenv("CRM_DB_USER", DB_USER)
CRM_DB_PASSWORD = os.getenv("CRM_DB_PASSWORD", DB_PASSWORD)

CRM_DATABASE_URL = f"postgresql://{CRM_DB_USER}:{CRM_DB_PASSWORD}@{CRM_DB_HOST}:{CRM_DB_PORT}/{CRM_DB_NAME}"


_primary_pool: Optional[asyncpg.Pool] = None
_crm_pool: Optional[asyncpg.Pool] = None


async def _init_pool(dsn: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        dsn,
        min_size=5,
        max_size=20,
        command_timeout=60,
    )
    # Enable pgvector if available
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    return pool


async def init_database():
    """Initialize database connection pools (primary + CRM)"""
    global _primary_pool, _crm_pool
    if _primary_pool is None:
        _primary_pool = await _init_pool(DATABASE_URL)
        print("✅ Database connection pool initialized")
    if _crm_pool is None:
        _crm_pool = await _init_pool(CRM_DATABASE_URL)
        print("✅ CRM database connection pool initialized")


def get_pool(which: str = "primary") -> asyncpg.Pool:
    """Get a connection pool by role: 'primary' or 'crm'"""
    if which == "crm":
        if _crm_pool is None:
            raise Exception("CRM database pool not initialized. Call init_database() first.")
        return _crm_pool
    # default primary
    if _primary_pool is None:
        raise Exception("Database pool not initialized. Call init_database() first.")
    return _primary_pool


@asynccontextmanager
async def get_db_connection(which: str = "primary"):
    """Get database connection from selected pool"""
    pool = get_pool(which)
    async with pool.acquire() as connection:
        yield connection


async def close_database():
    """Close database connection pools"""
    global _primary_pool, _crm_pool
    if _primary_pool:
        await _primary_pool.close()
        _primary_pool = None
    if _crm_pool:
        await _crm_pool.close()
        _crm_pool = None
