from src.i18n.translates import (
    TranslationData,
    get_registered_small_translates,
    register_small_translate,
    register_small_translates,
)

__all__ = ["register", "register_many", "get_registered"]


def register(key: str, data: TranslationData) -> None:
    register_small_translate(key, data)


def register_many(mapping: dict[str, TranslationData]) -> None:
    register_small_translates(mapping)


def get_registered() -> dict[str, TranslationData]:
    return get_registered_small_translates()
