from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.i18n.settings import LARGE_I18N_DATA_MAX_LENGTH, SMALL_I18N_DATA_MAX_LENGTH
from src.settings import APP


TranslationMap = dict[str, str]

DEFAULT_SMALL_I18N_EXAMPLE = {
    "key": "role.student.title",
    "data": {
        "en": "Student",
        "ru": "Student",
        "uz": "Student",
    },
}

DEFAULT_LARGE_I18N_EXAMPLE = {
    "key1": "course",
    "key2": "description",
    "data": {
        "en": "Course description text",
        "ru": "Course description text",
        "uz": "Course description text",
    },
}


class I18nSmallSchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": DEFAULT_SMALL_I18N_EXAMPLE
        }
    )

    key: str = Field(min_length=1, max_length=128)
    data: TranslationMap = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def validate_data_lengths(cls, value: TranslationMap) -> TranslationMap:
        return _validate_translation_map(value, SMALL_I18N_DATA_MAX_LENGTH)


class I18nLargeSchema(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": DEFAULT_LARGE_I18N_EXAMPLE
        }
    )

    # Keys are required fields, but empty string is allowed by business rules.
    key1: str = Field(max_length=128)
    key2: str = Field(max_length=128)
    data: TranslationMap = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def validate_data_lengths(cls, value: TranslationMap) -> TranslationMap:
        return _validate_translation_map(value, LARGE_I18N_DATA_MAX_LENGTH)


def _validate_translation_map(value: TranslationMap, max_length: int) -> TranslationMap:
    allowed_languages = set(APP.REQUIRED_LANGUAGES)
    for lang, text in value.items():
        if lang not in allowed_languages:
            raise ValueError(f"Unsupported language: {lang}")
        if not isinstance(text, str):
            raise ValueError(f"Translation for '{lang}' must be a string")
        if len(text) > max_length:
            raise ValueError(f"Translation for '{lang}' exceeds max length {max_length}")
    return value
