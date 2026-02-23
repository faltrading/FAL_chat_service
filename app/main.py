import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import groups, health, invites, messages, websocket_routes
from app.core.config import settings
from app.db.session import async_session_factory, engine
from app.services.gateway_client import close_gateway_client
from app.services.group_service import get_or_create_default_group

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        admin_user_id = uuid.uuid5(uuid.NAMESPACE_DNS, settings.ADMIN_USERNAME)
        async with async_session_factory() as db:
            await get_or_create_default_group(db, admin_user_id)
        logger.info("Default group initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize default group on startup: {e}")

    yield

    await websocket_routes.close_all_connections()
    await close_gateway_client()
    await engine.dispose()


app = FastAPI(
    title="Chat Pubblica - Microservizio",
    description="Microservizio per la gestione della chat pubblica e gruppi",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(groups.router)
app.include_router(messages.router)
app.include_router(invites.router)
app.include_router(websocket_routes.router)
