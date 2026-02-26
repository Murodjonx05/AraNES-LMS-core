TranslationData = dict[str, str]
SmallTranslates = dict[str, TranslationData]
LargeTranslateKey = tuple[str, str]
LargeTranslates = dict[LargeTranslateKey, TranslationData]

SMALL_TRANSLATES_REGISTRY: SmallTranslates = {}
LARGE_TRANSLATES_REGISTRY: LargeTranslates = {}


def register_small_translates(mapping: SmallTranslates) -> None:
    SMALL_TRANSLATES_REGISTRY.update({key: dict(value) for key, value in mapping.items()})


def register_small_translate(key: str, data: TranslationData) -> None:
    register_small_translates({key: data})


def get_registered_small_translates() -> SmallTranslates:
    return {key: dict(value) for key, value in SMALL_TRANSLATES_REGISTRY.items()}


def register_large_translates(mapping: LargeTranslates) -> None:
    LARGE_TRANSLATES_REGISTRY.update(
        {(key1, key2): dict(value) for (key1, key2), value in mapping.items()}
    )


def register_large_translate(key1: str, key2: str, data: TranslationData) -> None:
    register_large_translates({(key1, key2): data})


def get_registered_large_translates() -> LargeTranslates:
    return {
        (key1, key2): dict(value)
        for (key1, key2), value in LARGE_TRANSLATES_REGISTRY.items()
    }


# Backward-compatible aliases (current title-based usage maps to "small")
register_title_translates = register_small_translates
get_registered_title_translates = get_registered_small_translates
