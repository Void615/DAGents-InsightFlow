import logging
import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres import dict_row
from app.config import get_settings

logger = logging.getLogger(__name__)

_saver: AsyncPostgresSaver | None = None
_conn: psycopg.AsyncConnection | None = None


async def init_checkpointer() -> None:
    global _saver, _conn
    settings = get_settings()
    _conn = await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL_SYNC,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    _saver = AsyncPostgresSaver(conn=_conn)
    await _saver.setup()
    logger.info("Postgres checkpointer initialized")


async def get_checkpointer() -> AsyncPostgresSaver:
    if _saver is None:
        raise RuntimeError("Checkpointer not initialized")
    return _saver


async def shutdown_checkpointer() -> None:
    global _saver, _conn
    if _conn is not None:
        await _conn.close()
        _saver = None
        _conn = None
        logger.info("Postgres checkpointer connection closed")
