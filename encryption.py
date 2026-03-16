import os
from cryptography.fernet import Fernet

_raw_key = os.getenv("ENCRYPTION_KEY", "").strip()

if not _raw_key:
    raise RuntimeError(
        "ENCRYPTION_KEY is not set in your .env file.\n"
        "Generate one by running:\n"
        "  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
        "Then add it to your .env as: ENCRYPTION_KEY=your_key_here"
    )

_fernet = Fernet(_raw_key.encode())


def encrypt_data(data: str) -> bytes:
    return _fernet.encrypt(data.encode("utf-8"))


def decrypt_data(data: bytes) -> str:
    return _fernet.decrypt(data).decode("utf-8")


def save_encrypted(filepath: str, data: str) -> None:
    encrypted = encrypt_data(data)
    with open(filepath, "wb") as f:
        f.write(encrypted)


def load_encrypted(filepath: str) -> str:
    with open(filepath, "rb") as f:
        return decrypt_data(f.read())
