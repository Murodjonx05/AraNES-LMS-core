from src.i18n.translates import (
    TranslationData,
    get_registered_large_translates,
    register_large_translate,
    register_large_translates,
)

__all__ = ["register", "register_many", "get_registered"]


def register(key1: str, key2: str, data: TranslationData) -> None:
    register_large_translate(key1, key2, data)


def register_many(mapping: dict[tuple[str, str], TranslationData]) -> None:
    register_large_translates(mapping)


def get_registered() -> dict[tuple[str, str], TranslationData]:
    return get_registered_large_translates()
