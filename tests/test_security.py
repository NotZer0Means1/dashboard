from app.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_password_and_verify_success():
    hashed = hash_password("hunter2222")
    assert hashed != "hunter2222"
    assert verify_password("hunter2222", hashed)


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("hunter2222")
    assert not verify_password("wrong-password", hashed)


def test_create_and_decode_access_token_roundtrip():
    token = create_access_token(subject="alice")
    assert decode_access_token(token) == "alice"


def test_decode_access_token_rejects_garbage_token():
    assert decode_access_token("not-a-valid-token") is None
