"""Загрузка системного промпта Алины и базы знаний Zerocoder."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SYSTEM_PROMPT_PATH = BASE_DIR / "prompts" / "system_prompt.txt"
KNOWLEDGE_BASE_PATH = BASE_DIR / "knowledge" / "zerocoder_knowledge_base.md"

KNOWLEDGE_BASE_PLACEHOLDER = "[[KNOWLEDGE_BASE]]"
SALES_FORM_PLACEHOLDER = "[[SALES_FORM_URL]]"


def build_system_prompt(sales_form_url: str) -> str:
    """Собирает полный системный промпт: инструкции Алины + база знаний + ссылка на форму."""
    try:
        prompt_template = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"Не найден файл системного промпта: {SYSTEM_PROMPT_PATH}")

    try:
        knowledge_base = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"Не найден файл базы знаний: {KNOWLEDGE_BASE_PATH}")

    return (
        prompt_template
        .replace(KNOWLEDGE_BASE_PLACEHOLDER, knowledge_base)
        .replace(SALES_FORM_PLACEHOLDER, sales_form_url.strip())
    )
