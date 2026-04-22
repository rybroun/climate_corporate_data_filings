from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    anthropic_api_key: str = ""
    serper_api_key: str = ""

    # Postgres connection (derived from Supabase or set directly)
    database_url: str = ""

    model_config = {
        "env_file": [
            "../.env",           # monorepo root
            "../../.env",        # project root (Watershed Take Home Docs/)
            ".env",              # backend dir itself
        ],
        "env_file_encoding": "utf-8",
        "extra": "ignore",      # ignore NEXT_PUBLIC_* and other frontend vars
    }


settings = Settings()
