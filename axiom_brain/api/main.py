"""
AxiomBrain — FastAPI Application Entry Point

Start with:
    uvicorn axiom_brain.api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from axiom_brain.config import get_settings
from axiom_brain.database.connection import close_pool, get_pool
from axiom_brain.database.neo4j import close_driver as close_neo4j, get_driver as get_neo4j_driver
from axiom_brain.api.routes import (
    health,
    ingest,
    search,
    graph,
    summarize,
    decay,
    dashboard,
    webhooks,
    workspaces,
)
from axiom_brain.jobs.summarize import run_summarization_job
from axiom_brain.jobs.decay import run_decay_job

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ModuleNotFoundError:
    AsyncIOScheduler = None  # type: ignore[assignment]

_scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler

    # Startup: warm up Postgres pool and Neo4j driver
    await get_pool()
    await get_neo4j_driver()

    # Start nightly background jobs (skipped in DEBUG / dev mode)
    settings = get_settings()
    if not settings.debug:
        if AsyncIOScheduler is None:
            logger.warning(
                "APScheduler not installed; nightly summarize/decay jobs disabled. "
                "Install with: pip install apscheduler"
            )
        else:
            _scheduler = AsyncIOScheduler()

            # 2:00 AM — summarization pipeline
            _scheduler.add_job(
                run_summarization_job,
                trigger="cron",
                hour=2,
                minute=0,
                id="nightly_summarize",
                replace_existing=True,
            )

            # 2:30 AM — decay score recalculation (offset to avoid DB contention)
            _scheduler.add_job(
                run_decay_job,
                trigger="cron",
                hour=2,
                minute=30,
                id="nightly_decay",
                replace_existing=True,
            )

            _scheduler.start()
            logger.info("Nightly jobs scheduled: summarize @ 02:00, decay @ 02:30")
    else:
        logger.info("DEBUG mode — nightly schedulers disabled")

    yield

    # Shutdown
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    await close_pool()
    await close_neo4j()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AxiomBrain — A shared persistent memory layer for LLM tools. "
            "Provides semantic storage and retrieval across Claude Code, Codex, "
            "Cursor, and custom AI agents."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — restrict in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else ["http://localhost:*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router,     tags=["Health"])
    app.include_router(ingest.router,     tags=["Memory"])
    app.include_router(search.router,     tags=["Memory"])
    app.include_router(graph.router,      tags=["Graph"])
    app.include_router(summarize.router,  tags=["Summarization"])
    app.include_router(decay.router,      tags=["Decay"])
    app.include_router(dashboard.router,  tags=["Dashboard"])
    app.include_router(webhooks.router,    tags=["Webhooks"])
    app.include_router(workspaces.router)  # prefix + tags defined in the router

    return app


app = create_app()
