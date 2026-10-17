"""Конфигурация бота: чтение секретов и настроек из переменных окружения (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

DEFAULT_SALES_FORM_URL = "https://zerocoder.ru/"
DEFAULT_GIGACHAT_SCOPE = "GIGACHAT_API_PERS"
DEFAULT_GIGACHAT_MODEL = "GigaChat-2-Pro"
DEFAULT_HISTORY_LIMIT = 12


@dataclass(frozen=True)
class Settings:
    vk_group_token: str
    vk_group_id: int | None
    gigachat_auth_key: str
    gigachat_scope: str
    gigachat_model: str
    gigachat_ca_bundle: str | None
    sales_form_url: str
    history_limit: int


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def load_settings() -> Settings:
    """Проверяет обязательные переменные и возвращает настройки бота.

    Реальные значения секретов хранятся только в .env (см. .env.example и README.md).
    """
    required = ["VK_GROUP_TOKEN", "GIGACHAT_AUTH_KEY"]
    missing = [name for name in required if not _get(name)]
    if missing:
        names = ", ".join(missing)
        raise SystemExit(
            f"Не заданы обязательные переменные окружения: {names}.\n"
            f"Скопируйте .env.example в .env и заполните значения (инструкция в README.md)."
        )

    group_id_raw = _get("VK_GROUP_ID")
    group_id: int | None = None
    if group_id_raw:
        try:
            group_id = int(group_id_raw)
        except ValueError:
            raise SystemExit("VK_GROUP_ID должен быть числом (ID сообщества ВКонтакте).")

    history_limit_raw = _get("HISTORY_LIMIT", str(DEFAULT_HISTORY_LIMIT))
    try:
        history_limit = max(2, int(history_limit_raw))
    except ValueError:
        history_limit = DEFAULT_HISTORY_LIMIT

    return Settings(
        vk_group_token=_get("VK_GROUP_TOKEN"),
        vk_group_id=group_id,
        gigachat_auth_key=_get("GIGACHAT_AUTH_KEY"),
        gigachat_scope=_get("GIGACHAT_SCOPE", DEFAULT_GIGACHAT_SCOPE) or DEFAULT_GIGACHAT_SCOPE,
        gigachat_model=_get("GIGACHAT_MODEL", DEFAULT_GIGACHAT_MODEL) or DEFAULT_GIGACHAT_MODEL,
        gigachat_ca_bundle=_get("GIGACHAT_CA_BUNDLE") or None,
        sales_form_url=_get("SALES_FORM_URL", DEFAULT_SALES_FORM_URL) or DEFAULT_SALES_FORM_URL,
        history_limit=history_limit,
    )
