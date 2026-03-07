from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.i18n.models import TranslateDesc, TranslateTitle
from src.i18n.translates import (
    get_registered_large_translates,
    get_registered_small_translates,
)


_TRANSLATE_REGISTRARS_IMPORTED = False


def _import_translate_registrars() -> None:
    global _TRANSLATE_REGISTRARS_IMPORTED
    if _TRANSLATE_REGISTRARS_IMPORTED:
        return
    # Import modules that register translations into the i18n registry.
    import src.user_role.translates  # noqa: F401
    _TRANSLATE_REGISTRARS_IMPORTED = True


def ensure_translate_registrars_loaded() -> None:
    """Load modules that register i18n translations into the global registry."""
    _import_translate_registrars()


async def seed_small_i18n_titles_if_missing(session: AsyncSession, *, commit: bool = True) -> int:
    ensure_translate_registrars_loaded()

    result = await session.execute(select(TranslateTitle.key))
    existing = set(result.scalars().all())
    registered_titles = get_registered_small_translates()

    created = 0
    to_add = []
    for translate_key, translate_data in registered_titles.items():
        if translate_key in existing:
            continue

        to_add.append(TranslateTitle(key=translate_key, title=dict(translate_data)))
        created += 1
    if to_add:
        session.add_all(to_add)

    if created and commit:
        await session.commit()

    return created


async def seed_large_i18n_descriptions_if_missing(
    session: AsyncSession,
    *,
    commit: bool = True,
) -> int:
    ensure_translate_registrars_loaded()

    result = await session.execute(select(TranslateDesc.key1, TranslateDesc.key2))
    existing = set(result.all())
    registered_descriptions = get_registered_large_translates()

    created = 0
    to_add = []
    for (key1, key2), translate_data in registered_descriptions.items():
        if (key1, key2) in existing:
            continue

        to_add.append(
            TranslateDesc(
                key1=key1,
                key2=key2,
                description=dict(translate_data),
            )
        )
        created += 1
    if to_add:
        session.add_all(to_add)

    if created and commit:
        await session.commit()

    return created


# Backward-compatible alias
seed_role_i18n_titles_if_missing = seed_small_i18n_titles_if_missing
