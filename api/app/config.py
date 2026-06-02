from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env.

    Every exchange integration is optional: with no API keys an exchange is
    still listed and connectable by UID, but cashback accrual stays off for it
    (there is no rebate stream to reconstruct the user's fee from).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    database_url: str = "postgresql+asyncpg://cashback:cashback@localhost:5432/cashback"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "dev-secret-change-in-production"
    env: str = "development"
    log_level: str = "INFO"

    # --- Telegram ---
    # Bot token from @BotFather. Empty in demo / frontend-only deploys.
    tg_bot_token: str = ""
    # bot_username — used to build referral links (t.me/<username>?start=ref_...)
    tg_bot_username: str = "your_cashback_bot"
    # Public domain the Mini App is served from (CORS + bot WebApp button).
    web_domain: str = "localhost:8080"

    # --- BingX (Broker / Affiliate program) ---
    bingx_api_key: str = ""
    bingx_api_secret: str = ""
    bingx_base_url: str = "https://open-api.bingx.com"
    bingx_recv_window_ms: int = 5000
    bingx_default_referral_url: str = ""

    # --- Binance (API Partner / apiReferral, email-based) ---
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_base_url: str = "https://api.binance.com"
    binance_fapi_url: str = "https://fapi.binance.com"
    binance_recv_window_ms: int = 5000
    binance_api_agent_code: str = ""
    # Our share of the referral's fee on Binance Link (e.g. "0.40"). Needed to
    # reconstruct the user's fee from our income. Empty/"0" → accrual off.
    binance_rebate_rate: str = "0"
    binance_default_referral_url: str = ""

    # --- Bitget (Agent / Affiliate, UID-based, needs passphrase) ---
    bitget_api_key: str = ""
    bitget_api_secret: str = ""
    bitget_api_passphrase: str = ""
    bitget_base_url: str = "https://api.bitget.com"
    bitget_rebate_rate: str = "0"
    bitget_default_referral_url: str = ""

    # --- MEXC (Affiliate / Broker, UID-based, no passphrase) ---
    mexc_api_key: str = ""
    mexc_api_secret: str = ""
    mexc_base_url: str = "https://api.mexc.com"
    mexc_rebate_rate: str = "0"
    mexc_default_referral_url: str = ""

    # --- BYDFi (Affiliate / Agent, UID-based, hex-HMAC headers; base needs /api) ---
    bydfi_api_key: str = ""
    bydfi_api_secret: str = ""
    bydfi_base_url: str = "https://api.bydfi.com/api"
    bydfi_rebate_rate: str = "0"
    bydfi_default_referral_url: str = ""

    # --- Withdrawals ---
    withdrawal_min_usd: float = 1.0
    withdrawal_daily_limit_usd: float = 5000.0
    withdrawal_monthly_limit_usd: float = 20000.0
    withdrawal_cooldown_minutes: int = 30

    # --- Demo ---
    # When the database has only a handful of real users/withdrawals, the public
    # showcase endpoints (global stats, leaderboard, recent withdrawals) fall
    # back to deterministic demo data so the app never looks empty. Set
    # DEMO_SOCIAL_PROOF=false to serve only real figures.
    demo_social_proof: bool = True


settings = Settings()
