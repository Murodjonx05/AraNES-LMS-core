from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.i18n.exceptions import I18nLargeNotFoundError, I18nSmallNotFoundError
from src.i18n.models import TranslateDesc, TranslateTitle
from src.i18n.translates import register_large_translate, register_small_translate

TranslationPatch = dict[str, str]


def _merge_translation_patch(
    current_translation_map: TranslationPatch | None,
    translation_patch: TranslationPatch,
) -> TranslationPatch:
    merged_translation_map = dict(current_translation_map or {})
    merged_translation_map.update(dict(translation_patch))
    return merged_translation_map


async def list_small(session: AsyncSession) -> list[TranslateTitle]:
    result = await session.execute(select(TranslateTitle).order_by(TranslateTitle.key))
    return list(result.scalars().all())


async def get_small_optional(session: AsyncSession, key: str) -> TranslateTitle | None:
    return await session.get(TranslateTitle, key)


async def get_small_by_key(session: AsyncSession, key: str) -> TranslateTitle:
    db_small_translation = await get_small_optional(session, key)
    if db_small_translation is None:
        raise I18nSmallNotFoundError("i18n small data not found")
    return db_small_translation


async def upsert_small(
    session: AsyncSession,
    *,
    key: str,
    translation_patch: TranslationPatch,
) -> TranslateTitle:
    db_small_translation = await get_small_optional(session, key)
    if db_small_translation is None:
        db_small_translation = TranslateTitle(key=key, title=dict(translation_patch))
        session.add(db_small_translation)
    else:
        db_small_translation.title = _merge_translation_patch(
            db_small_translation.title,
            translation_patch,
        )

    await session.commit()
    return db_small_translation


async def register_and_upsert_small(
    session: AsyncSession,
    *,
    key: str,
    translation_patch: TranslationPatch,
) -> TranslateTitle:
    register_small_translate(key, translation_patch)
    return await upsert_small(session, key=key, translation_patch=translation_patch)


async def list_large(session: AsyncSession) -> list[TranslateDesc]:
    result = await session.execute(
        select(TranslateDesc).order_by(TranslateDesc.key1, TranslateDesc.key2)
    )
    return list(result.scalars().all())


async def get_large_optional(
    session: AsyncSession,
    *,
    key1: str,
    key2: str,
) -> TranslateDesc | None:
    return await session.get(TranslateDesc, {"key1": key1, "key2": key2})


async def get_large(
    session: AsyncSession,
    *,
    key1: str,
    key2: str,
) -> TranslateDesc:
    db_large_translation = await get_large_optional(session, key1=key1, key2=key2)
    if db_large_translation is None:
        raise I18nLargeNotFoundError("i18n large data not found")
    return db_large_translation


async def upsert_large(
    session: AsyncSession,
    *,
    key1: str,
    key2: str,
    translation_patch: TranslationPatch,
) -> TranslateDesc:
    db_large_translation = await get_large_optional(session, key1=key1, key2=key2)
    if db_large_translation is None:
        db_large_translation = TranslateDesc(
            key1=key1,
            key2=key2,
            description=dict(translation_patch),
        )
        session.add(db_large_translation)
    else:
        db_large_translation.description = _merge_translation_patch(
            db_large_translation.description,
            translation_patch,
        )

    await session.commit()
    return db_large_translation


async def register_and_upsert_large(
    session: AsyncSession,
    *,
    key1: str,
    key2: str,
    translation_patch: TranslationPatch,
) -> TranslateDesc:
    register_large_translate(key1, key2, translation_patch)
    return await upsert_large(
        session,
        key1=key1,
        key2=key2,
        translation_patch=translation_patch,
    )
