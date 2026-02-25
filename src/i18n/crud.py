from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.i18n.exceptions import I18nLargeNotFoundError, I18nSmallNotFoundError
from src.i18n.models import TranslateDesc, TranslateTitle

TranslationPatch = dict[str, str]


def _merge_translation_patch(
    current_translation_map: TranslationPatch | None,
    translation_patch: TranslationPatch,
) -> TranslationPatch:
    merged_translation_map = dict(current_translation_map or {})
    merged_translation_map.update(dict(translation_patch))
    return merged_translation_map


async def list_small(session: AsyncSession) -> list[TranslateTitle]:
    query_result = await session.execute(select(TranslateTitle))
    return list(query_result.scalars().all())


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
    else:
        db_small_translation.title = _merge_translation_patch(
            db_small_translation.title,
            translation_patch,
        )

    session.add(db_small_translation)
    await session.commit()
    await session.refresh(db_small_translation)
    return db_small_translation


async def list_large(session: AsyncSession) -> list[TranslateDesc]:
    query_result = await session.execute(select(TranslateDesc))
    return list(query_result.scalars().all())


async def get_large_optional(
    session: AsyncSession,
    *,
    key1: str,
    key2: str,
) -> TranslateDesc | None:
    query_result = await session.execute(
        select(TranslateDesc).where(
            TranslateDesc.key1 == key1,
            TranslateDesc.key2 == key2,
        )
    )
    return query_result.scalar_one_or_none()


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
    else:
        db_large_translation.description = _merge_translation_patch(
            db_large_translation.description,
            translation_patch,
        )

    session.add(db_large_translation)
    await session.commit()
    await session.refresh(db_large_translation)
    return db_large_translation
