import hashlib


def sha256_hex(value: str) -> str:
    # For random tokens and short-lived codes with attempt limits; passwords use Argon2.
    return hashlib.sha256(value.encode()).hexdigest()
