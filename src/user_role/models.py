from src.database import Model
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, JSON, ForeignKey


class Role(Model):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Can be an empty string when a role has no i18n title binding yet.
    title_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    permissions: Mapped[dict[str, bool]] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True,
    )

    users: Mapped[list["User"]] = relationship("User", back_populates="role")


class User(Model):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    permissions: Mapped[dict[str, bool]] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True,
    )

    role: Mapped["Role"] = relationship("Role", back_populates="users")
