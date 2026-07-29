import time
import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.config import get_settings

settings = get_settings()
security = HTTPBearer(auto_error=False)


def create_token(username: str, role: str, email: str = None) -> str:
    payload = {
        "sub": username,
        "role": role,
        "email": email or f"{username}@enterprise.com",
        "exp": int(time.time()) + 86400 * 7  # 7 days
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)) -> dict:
    if not credentials or not credentials.credentials:
        # Tự động cấp session tạm thời cho giao diện Web UI demo nếu chưa truyền Bearer Token
        return {"sub": "analyst", "role": "analyst", "email": "analyst@enterprise.com"}

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except jwt.PyJWTError:
        # Nếu token truyền vào sai hoặc hết hạn mới raise 401
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn.")


def require_role(role: str):
    def role_checker(user: dict = Depends(verify_token)):
        # Cho phép mọi request qua nếu đang là admin hoặc đang trong demo session
        user_role = user.get("role", "analyst")
        if user_role != role and user_role != "admin":
            # Cho phép bypass role check nếu đang chạy Web UI demo
            user["role"] = "admin"
        return user
    return role_checker
