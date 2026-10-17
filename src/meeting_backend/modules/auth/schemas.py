from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=48, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128, repr=False)


class CreateUser(Login):
    password: str = Field(min_length=10, max_length=128, repr=False)
    display_name: str = Field(min_length=1, max_length=200)
    role: Literal["user", "admin"] = "user"


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(None, min_length=1, max_length=200)
    role: Literal["user", "admin"] | None = None
    active: bool | None = None


class PasswordChange(BaseModel):
    password: str = Field(min_length=10, max_length=128, repr=False)
    current_password: str | None = Field(None, max_length=128, repr=False)
