"""Клиент GigaChat API (официальная документация GigaChat, папка Gigachat_api).

Реализация на чистом requests без SDK:
  1. Токен доступа: POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth
     (заголовок Authorization: Basic <ключ авторизации>, поле scope, токен живёт 30 минут).
  2. Генерация ответа: POST https://api.giga.chat/v1/chat/completions
     (заголовок Authorization: Bearer <токен доступа>).
  3. Для запросов нужен корневой сертификат НУЦ Минцифры — скачивается автоматически.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://api.giga.chat/v1/chat/completions"
CA_CERT_URL = "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"
CA_CERT_PATH = Path(__file__).resolve().parent / "certs" / "russian_trusted_root_ca_pem.crt"

TOKEN_REFRESH_MARGIN_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 120


class GigaChatError(RuntimeError):
    """Ошибка при обращении к GigaChat API."""


def ensure_ca_certificate() -> Path:
    """Возвращает путь к корневому сертификату НУЦ Минцифры, при необходимости скачивает его.

    Сертификат публичный (не секрет) и хранится в папке certs/, которая добавлена в .gitignore.
    """
    if CA_CERT_PATH.exists() and CA_CERT_PATH.stat().st_size > 0:
        return CA_CERT_PATH

    CA_CERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(CA_CERT_URL, timeout=30)
        response.raise_for_status()
    except requests.exceptions.SSLError:
        # Документация GigaChat рекомендует скачивать сертификат с -k (без проверки),
        # сам сертификат публичный — повторяем загрузку без проверки цепочки.
        response = requests.get(CA_CERT_URL, timeout=30, verify=False)
        response.raise_for_status()

    CA_CERT_PATH.write_bytes(response.content.rstrip() + b"\n")
    logger.info("Сертификат НУЦ Минцифры сохранён: %s", CA_CERT_PATH)
    return CA_CERT_PATH


class GigaChatClient:
    """Обёртка над GigaChat API: автоматически получает и обновляет токен доступа."""

    def __init__(
        self,
        credentials: str,
        scope: str = "GIGACHAT_API_PERS",
        model: str = "GigaChat-2-Pro",
        ca_bundle: str | None = None,
    ) -> None:
        self._credentials = credentials
        self._scope = scope
        self._model = model
        self._ca_bundle = ca_bundle or str(ensure_ca_certificate())
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def model(self) -> str:
        return self._model

    def _fetch_token(self) -> None:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {self._credentials}",
        }
        try:
            response = requests.post(
                OAUTH_URL,
                headers=headers,
                data={"scope": self._scope},
                verify=self._ca_bundle,
                timeout=30,
            )
        except requests.exceptions.SSLError as exc:
            raise GigaChatError(
                "Ошибка SSL при получении токена. Проверьте сертификат НУЦ Минцифры "
                "(подробности в README.md, раздел «Сертификаты»)."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise GigaChatError(f"Сетевая ошибка при получении токена GigaChat: {exc}") from exc

        if response.status_code != 200:
            raise GigaChatError(
                f"GigaChat OAuth: HTTP {response.status_code} — проверьте ключ авторизации "
                f"GIGACHAT_AUTH_KEY и scope «{self._scope}»."
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise GigaChatError("GigaChat OAuth: в ответе нет access_token.")

        expires_at = float(payload.get("expires_at") or 0)
        if expires_at > 10**12:  # API возвращает время и в миллисекундах, и в секундах
            expires_at /= 1000.0
        if expires_at <= time.time():
            expires_at = time.time() + 30 * 60

        self._token = token
        self._token_expires_at = expires_at

    def _ensure_token(self) -> None:
        if not self._token or time.time() >= self._token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS:
            self._fetch_token()

    def chat(self, messages: list[dict]) -> str:
        """Отправляет диалог в модель и возвращает текст ответа ассистента.

        :param messages: список сообщений вида {"role": "system"|"user"|"assistant", "content": "..."}
        """
        self._ensure_token()

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

        for attempt in range(2):
            try:
                response = requests.post(
                    CHAT_URL,
                    headers=headers,
                    json=payload,
                    verify=self._ca_bundle,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.exceptions.SSLError as exc:
                raise GigaChatError(
                    "Ошибка SSL при запросе к GigaChat API. Проверьте сертификат НУЦ Минцифры."
                ) from exc
            except requests.exceptions.RequestException as exc:
                raise GigaChatError(f"Сетевая ошибка GigaChat API: {exc}") from exc

            if response.status_code == 401 and attempt == 0:
                # Токен истёк — получаем новый и повторяем запрос один раз.
                self._token = None
                self._ensure_token()
                headers["Authorization"] = f"Bearer {self._token}"
                continue

            if response.status_code == 429:
                raise GigaChatError("GigaChat API: превышен лимит запросов, попробуйте позже.")
            if response.status_code != 200:
                raise GigaChatError(f"GigaChat chat/completions: HTTP {response.status_code}")

            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise GigaChatError("GigaChat API: неожиданный формат ответа.") from exc

            if not content or not str(content).strip():
                raise GigaChatError("GigaChat API: пустой ответ модели.")
            return str(content).strip()

        raise GigaChatError("GigaChat API: не удалось получить ответ модели.")
