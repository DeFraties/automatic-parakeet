"""Application settings, loaded from environment variables / the repo-root `.env` file."""

from datetime import date
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Game constants (Section 3.1). Kept as module constants so they're trivially importable.
MAX_POINTS = 5000
ZERO_POINT_RATIO = 3.0
ROUNDS_PER_GAME = 5

# Guess / slider range in USD (Section 2.6).
USD_SLIDER_MIN = 5_000
USD_SLIDER_MAX = 50_000_000

# Eligibility price bounds in USD (Section 5.3).
ELIGIBLE_USD_MIN = 5_000
ELIGIBLE_USD_MAX = 100_000_000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/ballpark.db"
    daily_salt: str = "change-me"
    launch_date: date = date(2027, 1, 1)
    public_base_url: str = "https://ballpark.example.com"
    contact_email: str = "you@example.com"
    scraper_user_agent: str = "BallparkBot/1.0"
    cors_origins: str = "http://localhost:5173"
    max_price_age_years: int = 2  # asking prices go stale fast
    min_pool_per_option: int = 50

    # Listing photos (Section 5.1 / 7)
    max_photos_stored: int = 10
    max_photos_per_round: int = 6
    min_ok_photos: int = 2

    # Refresh (Section 8.7)
    refresh_days: int = 14
    refresh_daily_limit: int = 500

    ghsl_smod_path: str = "./data/ghsl/GHS_SMOD.tif"
    ghsl_smod_url: str = (
        "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_SMOD_GLOBE_R2023A/"
        "GHS_SMOD_E2025_GLOBE_R2023A_54009_1000/V2-0/GHS_SMOD_E2025_GLOBE_R2023A_54009_1000_V2_0.zip"
    )
    fx_manual_csv: str = "./data/fx_manual.csv"
    fx_api_url: str = "https://api.frankfurter.dev/v1"
    ingest_cache_dir: str = "./data/cache"

    # Mini map tiles (Section 4.2 / 11). Swap for another provider if traffic grows.
    osm_tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = (
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    )

    # Rate limits per IP per hour (Section 6.1). 0 disables.
    rate_limit_games_per_hour: int = 30
    rate_limit_guesses_per_hour: int = 120
    rate_limit_writes_per_hour: int = 30  # leaderboard submissions, reports, removals, telemetry

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
