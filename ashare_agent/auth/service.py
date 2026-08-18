from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel

from ashare_agent.storage import ApplicationRepository, UserRecord

from .password import hash_password, verify_password


class AuthenticationError(ValueError):
    pass


class AuthenticatedUser(BaseModel):
    id: str
    username: str
    display_name: str


class AuthService:
    def __init__(
        self,
        repository: ApplicationRepository,
        *,
        secret: str,
        expire_hours: int,
        demo_username: str,
        demo_password: str,
        demo_display_name: str,
    ):
        self._repository = repository
        self._secret = secret
        self._expire_hours = expire_hours
        self._demo_username = demo_username
        self._demo_password = demo_password
        self._demo_display_name = demo_display_name

    async def initialize(self) -> None:
        await self._repository.create_user(
            self._demo_username,
            self._demo_display_name,
            hash_password(self._demo_password),
        )

    async def login(
        self,
        username: str,
        password: str,
    ) -> tuple[str, AuthenticatedUser]:
        user = await self._repository.get_user_by_username(username.strip())
        if (
            user is None
            or not user.is_active
            or not verify_password(password, user.password_hash)
        ):
            raise AuthenticationError("用户名或密码错误。")
        return self._create_token(user), _public_user(user)

    async def authenticate(self, token: str) -> AuthenticatedUser:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
            )
            user_id = payload["sub"]
            if not isinstance(user_id, str) or not user_id:
                raise ValueError
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise AuthenticationError("登录凭证无效或已过期。") from exc

        user = await self._repository.get_user_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("用户不存在或已禁用。")
        return _public_user(user)

    def _create_token(self, user: UserRecord) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": user.id,
                "username": user.username,
                "iat": now,
                "exp": now + timedelta(hours=self._expire_hours),
            },
            self._secret,
            algorithm="HS256",
        )


def _public_user(user: UserRecord) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
    )
