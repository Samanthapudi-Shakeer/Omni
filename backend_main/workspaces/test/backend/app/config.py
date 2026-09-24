from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8080
    # Root directory under which each named workspace gets its own
    # subdirectory + its own independent Aider session/process.
    workspaces_root: str = "./workspaces"
    aider_bin: str = "aider"
    ollama_api_base: str = "http://127.0.0.1:11434"
    default_model: str = "ollama/qwen2.5-coder:32b"
    default_mode: str = "code"
    max_upload_mb: int = 50
    access_token: str = ""
    # Passed to Aider as --lint-cmd so its native /lint command (used by the
    # "Lint & Auto-fix" action) actually runs pylint rather than whatever
    # linter Aider would otherwise auto-detect for the language. Aider's
    # own format is "<language>: <command>", e.g. "python: pylint".
    lint_cmd: str = "python: pylint"

    @property
    def workspaces_root_path(self) -> Path:
        p = Path(self.workspaces_root).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()

