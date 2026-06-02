import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import exchanges, me, referral, stats, withdrawals

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("api")

app = FastAPI(title="Cashback Mini App API", version="1.0.0")

# Mini App is opened inside Telegram from the configured web domain; localhost
# origins keep `npm run dev` / `vite preview` working against a local API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"https://{settings.web_domain}",
        "http://localhost:5173",
        "http://localhost:4173",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)
app.include_router(exchanges.router)
app.include_router(referral.router)
app.include_router(stats.router)
app.include_router(withdrawals.router)


@app.get("/health")
async def health():
    # A light DB ping keeps the connection pool warm: the docker healthcheck
    # hits this every 30s so the first user request never pays a cold connect.
    from sqlalchemy import text

    from app.db import SessionLocal

    db_ok = True
    try:
        async with SessionLocal() as s:
            await s.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
        log.exception("health: db ping failed")
    return {"status": "ok", "env": settings.env, "db": db_ok}
