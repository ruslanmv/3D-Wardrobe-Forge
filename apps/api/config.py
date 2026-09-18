from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    wardrobe_provider: str = "template"
    wardrobe_storage_backend: str = "local"
    wardrobe_storage_root: str = "/data/wardrobe"
    wardrobe_job_backend: str = "memory"
    meshy_api_key: str = ""
    tripo_api_key: str = ""


settings = Settings()
