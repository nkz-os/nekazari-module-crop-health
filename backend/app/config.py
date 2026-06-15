"""
Crop Health Module — Configuration

Environment-based configuration using pydantic-settings.
All secrets via env vars / K8s Secrets — never hardcoded.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "Crop Health Engine"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # ── API ───────────────────────────────────────────────────────────────────
    api_prefix: str = "/api/crop-health"
    cors_origins: list[str] = []  # Empty = deny all cross-origin

    # ── Keycloak / JWT ────────────────────────────────────────────────────────
    keycloak_url: str = ""  # e.g. https://auth.robotika.cloud/auth
    keycloak_realm: str = "nekazari"
    jwt_audience: str = "account"
    jwt_issuer: str = ""  # Auto-derived if empty

    # ── Redis (shared instance, logical isolation via key prefix) ─────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    redis_key_prefix: str = "crophealth:"
    sliding_window_hours: int = 48  # Hours of dendrómetro data to retain

    # ── External Services ────────────────────────────────────────────────────
    orion_ld_url: str = "http://orion-ld-service:1026"
    orion_ld_context: str = "http://api-gateway-service:5000/ngsi-ld-context.json"
    bioorchestrator_url: str = "http://bioorchestrator-api-service:8420"
    weather_api_url: str = "http://timeseries-reader-service:5000"
    weather_db_url: str = ""  # deprecated — use weather_api_url instead
    soil_module_url: str = "http://soil-module-service:8000"
    self_url: str = "http://crop-health-backend-service:8000"  # this module's in-cluster base URL (for Orion notification callbacks)

    # ── Cache TTLs (seconds) ─────────────────────────────────────────────────
    phenology_cache_ttl: int = 3600  # 1h — phenology params change slowly
    weather_cache_ttl: int = 300     # 5min — weather data refreshes hourly

    # ── Service-to-service auth ──────────────────────────────────────────────
    module_management_key: str = ""
    internal_service_secret: str = ""

    @property
    def jwt_issuer_url(self) -> str:
        if self.jwt_issuer:
            return self.jwt_issuer
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    @property
    def jwks_url(self) -> str:
        return f"{self.jwt_issuer_url}/protocol/openid-connect/certs"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
