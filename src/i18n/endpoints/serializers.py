from src.i18n.models import TranslateDesc, TranslateTitle


def serialize_small(item: TranslateTitle) -> dict:
    return {
        "key": item.key,
        "data": item.title or {},
    }


def serialize_large(item: TranslateDesc) -> dict:
    return {
        "key1": item.key1,
        "key2": item.key2,
        "data": item.description or {},
    }
