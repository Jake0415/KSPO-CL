"""POST /api/auth/change-password + password.persist override 단위 테스트."""
from __future__ import annotations

import bcrypt
import pytest
from fastapi import HTTPException

from kspo_ingest.api.auth import password as pw_mod
from kspo_ingest.api.routers import auth as auth_router


def _bcrypt(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=4)).decode("ascii")


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """storage_root를 tmp_path로 격리해서 admin_password.txt 영향 차단."""
    monkeypatch.setattr(pw_mod.settings, "storage_root", str(tmp_path))
    yield tmp_path


def test_get_active_hash_returns_settings_when_no_override(isolated_storage, monkeypatch):
    monkeypatch.setattr(pw_mod.settings, "admin_password_bcrypt", _bcrypt("oldpass"))
    h = pw_mod.get_active_hash()
    assert pw_mod.verify_password("oldpass", h)


def test_persist_new_hash_creates_override_file(isolated_storage):
    new_hash = _bcrypt("newpass")
    pw_mod.persist_new_hash(new_hash)
    p = isolated_storage / "admin_password.txt"
    assert p.is_file()
    assert p.read_text(encoding="utf-8").strip() == new_hash


def test_get_active_hash_reads_override_when_present(isolated_storage, monkeypatch):
    monkeypatch.setattr(pw_mod.settings, "admin_password_bcrypt", _bcrypt("oldpass"))
    new_hash = _bcrypt("newpass")
    pw_mod.persist_new_hash(new_hash)

    active = pw_mod.get_active_hash()
    assert active == new_hash
    assert pw_mod.verify_password("newpass")
    assert not pw_mod.verify_password("oldpass")


@pytest.mark.asyncio
async def test_change_password_wrong_current_returns_401(isolated_storage, monkeypatch):
    monkeypatch.setattr(pw_mod.settings, "admin_password_bcrypt", _bcrypt("currentpw"))
    body = auth_router.ChangePasswordRequest(
        current_password="WRONGpass", new_password="newpass1234"
    )

    class FakeRequest:
        session: dict = {}

    with pytest.raises(HTTPException) as exc:
        await auth_router.change_password(body=body, request=FakeRequest(), _admin="admin")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_change_password_success_persists_and_clears_session(isolated_storage, monkeypatch):
    monkeypatch.setattr(pw_mod.settings, "admin_password_bcrypt", _bcrypt("currentpw"))

    class FakeRequest:
        def __init__(self):
            self.session = {"admin": {"u": "admin", "iat": 12345}}

    req = FakeRequest()
    body = auth_router.ChangePasswordRequest(
        current_password="currentpw", new_password="newPass!@34"
    )
    resp = await auth_router.change_password(body=body, request=req, _admin="admin")
    assert resp.status_code == 204
    # override file 생성됨 + 세션 삭제됨
    assert (isolated_storage / "admin_password.txt").is_file()
    assert "admin" not in req.session
    # 새 비밀번호로 verify 성공
    assert pw_mod.verify_password("newPass!@34")
    assert not pw_mod.verify_password("currentpw")


@pytest.mark.asyncio
async def test_change_password_min_length_validated_by_pydantic():
    """8자 미만은 pydantic 단계에서 ValueError."""
    with pytest.raises(Exception):
        auth_router.ChangePasswordRequest(current_password="x", new_password="short")
