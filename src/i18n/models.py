from sqlalchemy import JSON, Index, String
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Model
from src.settings import APP

TranslationData = dict[str, str]


def build_empty_translation_data() -> TranslationData:
    return {lang: "" for lang in APP.REQUIRED_LANGUAGES}


class TranslateTitle(Model):
    __tablename__ = "translate_small"

    # Natural key is better here than an extra surrogate id for lookup-heavy i18n tables.
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[TranslationData] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=False,
        default=build_empty_translation_data,
    )


class TranslateDesc(Model):
    __tablename__ = "translate_large"
    __table_args__ = (
        # Composite key for reusable i18n pairs: (entity, field) or (namespace, key)
        Index("ix_translate_large_key1", "key1"),
        Index("ix_translate_large_key1_key2", "key1", "key2"),
    )

    key1: Mapped[str] = mapped_column(String(128), primary_key=True)
    key2: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[TranslationData] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=False,
        default=build_empty_translation_data,
    )
