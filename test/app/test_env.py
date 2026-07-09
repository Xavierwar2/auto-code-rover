import os

from app.env import normalize_proxy_env


def test_normalize_proxy_env_rewrites_socks5h(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:7891")
    monkeypatch.setenv("https_proxy", "socks5h://localhost:1080")

    normalize_proxy_env()

    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7891"
    assert os.environ["https_proxy"] == "socks5://localhost:1080"
