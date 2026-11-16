from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values

path = Path(__file__).resolve().parents[1] / ".env"
if not path.exists():
    raise SystemExit("Runtime .env must exist first")
if not dotenv_values(path).get("TOKEN_ENCRYPTION_KEY"):
    with path.open("a", encoding="utf-8") as f:
        f.write("\nTOKEN_ENCRYPTION_KEY=" + Fernet.generate_key().decode() + "\n")
print("Token encryption key is configured; value was not printed.")
