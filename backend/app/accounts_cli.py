"""Operator CLI for account bootstrap and recovery (run on the server, never exposed over HTTP).

  python -m app.accounts_cli create-admin --username jdoe --display-name "J. Doe" --email jdoe@agency.example
  python -m app.accounts_cli reset-link --username jdoe

Prints a one-time setup path to deliver to the person through an approved channel.
"""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError
from sqlalchemy import select

from app import audit
from app.config import get_settings
from app.db import get_engine, make_sessionmaker
from app.models import User, UserRole
from app.schemas.accounts import UserCreateIn
from app.services import accounts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.accounts_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="create a Program Administrator and print a setup link")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--email", required=True)
    reset = sub.add_parser("reset-link", help="disable a user's credentials and print a reset link")
    reset.add_argument("--username", required=True)
    args = parser.parse_args(argv)

    settings = get_settings()
    with make_sessionmaker(get_engine())() as db:
        if args.command == "create-admin":
            try:
                spec = UserCreateIn(
                    username=args.username,
                    display_name=args.display_name,
                    email=args.email,
                    global_roles=["program_admin"],
                )
            except ValidationError as exc:
                print(exc, file=sys.stderr)
                return 2
            if db.scalar(select(User.id).where(User.username == spec.username)):
                print(f"User {spec.username} already exists; use reset-link instead.", file=sys.stderr)
                return 1
            user = User(
                username=spec.username,
                display_name=spec.display_name,
                email=str(spec.email).lower(),
                is_synthetic=False,
                is_dev_persona=False,
                active=True,
            )
            user.roles = [UserRole(role="program_admin")]
            db.add(user)
            db.flush()
            audit.record(
                db,
                actor_id=None,
                action="user.create",
                entity_type="user",
                entity_id=user.id,
                details={"username": user.username, "global_roles": ["program_admin"], "via": "cli"},
            )
            db.commit()
            purpose = "enroll"
        else:
            user = db.scalar(select(User).where(User.username == args.username.strip().lower()))
            if user is None:
                print("No such user.", file=sys.stderr)
                return 1
            purpose = "reset"
        # The CLI operator acts as the issuer of record for the link.
        raw = accounts.issue_setup_token(db, user.id, user, purpose, settings)
        print(
            f"One-time {purpose} link for {user.username} (valid {settings.setup_token_seconds // 3600} h):"
        )
        print(f"  /setup#token={raw}")
        print("Prefix with the site origin and deliver through an approved channel. It works once.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
