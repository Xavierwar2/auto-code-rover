import os
from pathlib import Path

from dotenv import load_dotenv


PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def normalize_proxy_env() -> None:
    """Normalize proxy env vars for libraries backed by httpx.

    httpx accepts socks5:// but rejects curl-style socks5h:// proxy URLs.
    """
    for key in PROXY_ENV_VARS:
        value = os.environ.get(key)
        if value and value.lower().startswith("socks5h://"):
            os.environ[key] = f"socks5://{value[len('socks5h://'):]}"


def load_project_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)
    normalize_proxy_env()
