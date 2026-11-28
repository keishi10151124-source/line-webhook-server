"""Prints a password hash for OWNER_PASSWORD_HASH. The password is read without echo."""
import getpass

from werkzeug.security import generate_password_hash

pw = getpass.getpass("password: ")
if len(pw) < 12:
    raise SystemExit("use at least 12 characters")
print(generate_password_hash(pw))
