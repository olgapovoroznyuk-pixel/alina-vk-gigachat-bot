"""Бот сообщества ВКонтакте для Zerocoder («Алина»).

Получает входящие сообщения сообщества через Bots Long Poll API ВКонтакте,
генерирует ответ через GigaChat API и отправляет его пользователю.

Запуск: python bot.py
"""

from __future__ import annotations

import json
import logging
import random
import sys
import time

import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.exceptions import ApiError

from config import load_settings
from gigachat_client import GigaChatClient, GigaChatError
from persona import build_system_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("zerocoder_bot")

FALLBACK_MESSAGE = (
    "Извините, что-то пошло не так, и я не смогла подготовить ответ. "
    "Пожалуйста, напишите ещё раз чуть позже. Если вопрос по обучению в Zerocoder — "
    "я с радостью помогу, когда связь наладится."
)
EMPTY_TEXT_MESSAGE = (
    "Пожалуйста, напишите ваш вопрос текстом — так я смогу вам лучше помочь! "
    "Я Алина, консультант онлайн-университета Zerocoder."
)


def build_keyboard(sales_form_url: str) -> str | None:
    """Клавиатура с кнопкой на форму подбора программы (если ссылка задана)."""
    if not sales_form_url:
        return None
    keyboard = {
        "one_time": False,
        "buttons": [
            [
                {
                    "action": {
                        "type": "open_link",
                        "link": sales_form_url,
                        "label": "Подобрать программу",
                    }
                }
            ]
        ],
    }
    return json.dumps(keyboard, ensure_ascii=False)


def ensure_longpoll_events(vk, group_id: int) -> None:
    """Включает подписку Long Poll на события сообщений.

    Без этого Long Poll может быть включён, но события не доставляются
    (в настройках сообщества не отмечены типы событий).
    """
    vk.groups.setLongPollSettings(
        group_id=group_id,
        enabled=1,
        message_new=1,
        message_reply=1,
        message_edit=1,
        message_allow=1,
        message_deny=1,
        message_typing_state=1,
    )
    logger.info("Long Poll: подписка на события сообщений включена.")


def resolve_group_id(vk_api_client, settings) -> int:
    """Определяет ID сообщества: из VK_GROUP_ID или автоматически по токену."""
    if settings.vk_group_id:
        return settings.vk_group_id

    info = vk_api_client.groups.getById()
    if isinstance(info, list) and info:
        return int(info[0]["id"])
    if isinstance(info, dict):
        if "groups" in info and info["groups"]:
            return int(info["groups"][0]["id"])
        if "id" in info:
            return int(info["id"])
    raise SystemExit(
        "Не удалось определить ID сообщества. Укажите VK_GROUP_ID в файле .env."
    )


def _trim_history(dialog: list[dict], limit: int) -> None:
    """Оставляет не более limit последних сообщений, начиная с реплики пользователя."""
    if len(dialog) <= limit:
        return
    excess = len(dialog) - limit
    if dialog[excess]["role"] == "assistant":
        excess += 1
    del dialog[:excess]


def handle_message(
    event,
    vk,
    gigachat: GigaChatClient,
    system_prompt: str,
    history: dict[int, list[dict]],
    settings,
    keyboard: str | None,
) -> None:
    message = event.message
    if message is None:
        # Некоторые версии API присылают само сообщение как объект события.
        obj = getattr(event, "object", None)
        message = obj if isinstance(obj, dict) and "peer_id" in obj else None
    if message is None:
        logger.warning("Сообщение без поля message, события пропущено: %s", event.raw)
        return

    peer_id = message.get("peer_id")
    from_id = message.get("from_id")
    text = (message.get("text") or "").strip()

    if peer_id is None:
        return

    # Сообщения самого сообщества пропускаем — защита от петли ответов.
    if from_id is not None and from_id < 0:
        return

    if not text:
        vk.messages.send(
            peer_id=peer_id,
            message=EMPTY_TEXT_MESSAGE,
            random_id=random.randint(1, 2**31),
            **({"keyboard": keyboard} if keyboard else {}),
        )
        return

    user_history = history.setdefault(peer_id, [])
    user_history.append({"role": "user", "content": text})
    _trim_history(user_history, settings.history_limit)

    messages_for_model = [{"role": "system", "content": system_prompt}, *user_history]

    try:
        reply = gigachat.chat(messages_for_model)
    except GigaChatError as exc:
        logger.error("Ошибка GigaChat для peer_id=%s: %s", peer_id, exc)
        reply = FALLBACK_MESSAGE

    user_history.append({"role": "assistant", "content": reply})
    _trim_history(user_history, settings.history_limit)

    vk.messages.send(
        peer_id=peer_id,
        message=reply,
        random_id=random.randint(1, 2**31),
        **({"keyboard": keyboard} if keyboard else {}),
    )
    logger.info("peer_id=%s | вопрос: %s... | ответ отправлен (%s симв.)",
                peer_id, text[:60], len(reply))


def main() -> None:
    settings = load_settings()
    system_prompt = build_system_prompt(settings.sales_form_url)
    keyboard = build_keyboard(settings.sales_form_url)

    gigachat = GigaChatClient(
        credentials=settings.gigachat_auth_key,
        scope=settings.gigachat_scope,
        model=settings.gigachat_model,
        ca_bundle=settings.gigachat_ca_bundle,
    )

    vk_session = vk_api.VkApi(token=settings.vk_group_token)
    vk = vk_session.get_api()

    group_id = resolve_group_id(vk, settings)
    history: dict[int, list[dict]] = {}

    try:
        ensure_longpoll_events(vk, group_id)
    except ApiError as exc:
        logger.warning(
            "Не удалось включить Long Poll-события автоматически: %s. "
            "Проверьте: Управление → Работа с API → Long Poll API → типы событий.",
            exc,
        )

    logger.info(
        "Бот Алина запущен | сообщество ID=%s | модель GigaChat: %s | scope: %s",
        group_id, gigachat.model, settings.gigachat_scope,
    )

    try:
        longpoll = VkBotLongPoll(vk_session, group_id)
    except ApiError as exc:
        if "longpoll" in str(exc).lower():
            raise SystemExit(
                "ВКонтакте: Long Poll не включён для сообщества.\n"
                "Включите: Управление сообществом → Работа с API → Long Poll API → включить.\n"
                "Подробности в README.md, раздел «Настройка сообщества ВКонтакте»."
            ) from exc
        raise

    while True:
        try:
            for event in longpoll.listen():
                logger.info("Событие Long Poll: %s | raw=%s", event.type, event.raw)
                if event.type == VkBotEventType.MESSAGE_NEW:
                    handle_message(
                        event=event,
                        vk=vk,
                        gigachat=gigachat,
                        system_prompt=system_prompt,
                        history=history,
                        settings=settings,
                        keyboard=keyboard,
                    )
        except ApiError as exc:
            logger.error("Ошибка VK API: %s", exc)
            time.sleep(3)
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем.")
            sys.exit(0)
        except Exception:
            logger.exception("Неожиданная ошибка, переподключение через 5 секунд...")
            time.sleep(5)


if __name__ == "__main__":
    main()
