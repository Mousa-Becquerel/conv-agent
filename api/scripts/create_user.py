"""Admin CLI: create an invite-only user account.

We deliberately don't expose a self-service /register endpoint — this CLI
is the only way to add accounts. Run it inside the api container:

    docker compose run --rm api python -m scripts.create_user \\
        --email alice@example.com \\
        --password 'choose-a-long-passphrase' \\
        --display-name "Alice" \\
        --admin

The password CAN also be piped on stdin (preferred — keeps it out of shell
history and `docker compose run` logs):

    echo -n 'my-passphrase' | docker compose run --rm -T api \\
        python -m scripts.create_user --email alice@example.com --stdin-password

On collision (same email already exists), use --update to reset the password
and toggle the admin flag instead of failing.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Optional

from sqlalchemy import select

from auth.passwords import hash_password
# Use the auth-scoped session so users are written to AUTH_DATABASE_URL
# (the shared Regalgrid users DB) when it's set; otherwise falls back to
# DATABASE_URL. In both cases this is the same DB the /auth/login endpoint
# reads from — never a schema mismatch.
from db.auth_session import AuthSessionLocal as SessionLocal
from db.models import User


def _read_password(args: argparse.Namespace) -> str:
    if args.password:
        return args.password
    if args.stdin_password:
        pw = sys.stdin.read()
        # Strip a single trailing newline only — passwords may legitimately
        # contain leading/trailing spaces.
        if pw.endswith("\n"):
            pw = pw[:-1]
        return pw
    # Interactive: prompt + confirm.
    pw = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm: ")
    if pw != confirm:
        print("ERROR: passwords do not match", file=sys.stderr)
        sys.exit(2)
    return pw


def main() -> int:
    p = argparse.ArgumentParser(description="Create or update a user account.")
    p.add_argument("--email", required=True, help="login email (lowercased on save)")
    pw = p.add_mutually_exclusive_group()
    pw.add_argument("--password", help="plaintext password (avoid — visible in shell history)")
    pw.add_argument("--stdin-password", action="store_true", help="read password from stdin")
    p.add_argument("--display-name", default=None)
    p.add_argument("--admin", action="store_true", help="grant is_admin=true")
    p.add_argument("--inactive", action="store_true", help="create the account disabled")
    p.add_argument(
        "--update",
        action="store_true",
        help="on conflict, update the existing user instead of failing",
    )
    args = p.parse_args()

    email = args.email.strip().lower()
    if "@" not in email:
        print(f"ERROR: '{email}' doesn't look like an email", file=sys.stderr)
        return 2

    plain_pw = _read_password(args)
    if len(plain_pw) < 8:
        print("ERROR: password must be at least 8 characters", file=sys.stderr)
        return 2

    pw_hash = hash_password(plain_pw)

    with SessionLocal() as db:
        existing: Optional[User] = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

        if existing and not args.update:
            print(
                f"ERROR: user with email '{email}' already exists. "
                "Use --update to overwrite.",
                file=sys.stderr,
            )
            return 3

        if existing:
            existing.password_hash = pw_hash
            if args.display_name is not None:
                existing.display_name = args.display_name
            existing.is_admin = args.admin
            existing.is_active = not args.inactive
            user = existing
            verb = "updated"
        else:
            user = User(
                email=email,
                password_hash=pw_hash,
                display_name=args.display_name,
                is_admin=args.admin,
                is_active=not args.inactive,
            )
            db.add(user)
            verb = "created"

        db.commit()
        db.refresh(user)

    print(
        f"OK: {verb} user id={user.id} email={user.email} "
        f"admin={user.is_admin} active={user.is_active}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
