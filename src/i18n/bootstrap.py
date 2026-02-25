from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.i18n.models import TranslateDesc, TranslateTitle
from src.i18n.translates import (
    get_registered_large_translates,
    get_registered_small_translates,
)


def _import_translate_registrars() -> None:
    # Import modules that register translations into the i18n registry.
    import src.user_role.translates  # noqa: F401


async def seed_small_i18n_titles_if_missing(session: AsyncSession) -> int:
    _import_translate_registrars()

    result = await session.execute(select(TranslateTitle))
    existing = {item.key for item in result.scalars().all()}
    registered_titles = get_registered_small_translates()

    created = 0
    for translate_key, translate_data in registered_titles.items():
        if translate_key in existing:
            continue

        session.add(TranslateTitle(key=translate_key, title=dict(translate_data)))
        created += 1

    if created:
        await session.commit()

    return created


async def seed_large_i18n_descriptions_if_missing(session: AsyncSession) -> int:
    _import_translate_registrars()

    result = await session.execute(select(TranslateDesc))
    existing = {(item.key1, item.key2) for item in result.scalars().all()}
    registered_descriptions = get_registered_large_translates()

    created = 0
    for (key1, key2), translate_data in registered_descriptions.items():
        if (key1, key2) in existing:
            continue

        session.add(
            TranslateDesc(
                key1=key1,
                key2=key2,
                description=dict(translate_data),
            )
        )
        created += 1

    if created:
        await session.commit()

    return created


# Backward-compatible alias
seed_role_i18n_titles_if_missing = seed_small_i18n_titles_if_missing
