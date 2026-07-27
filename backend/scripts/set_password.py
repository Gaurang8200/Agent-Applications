"""Set a user's password directly, from this machine.

The escape hatch for a forgotten password. There is no email-based reset flow
and there does not need to be: whoever can run this already has the database
and the filesystem, so it grants nothing they did not have.

    ./.venv/bin/python scripts/set_password.py you@example.com

The password is read from a hidden prompt, never taken as an argument, so it
does not land in shell history or the process list.
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402

MIN_LENGTH = 12


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} <email>", file=sys.stderr)
        return 2

    email = sys.argv[1].strip().lower()
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"No account for {email}.", file=sys.stderr)
            existing = [u.email for u in db.scalars(select(User)).all()]
            if existing:
                print("Known accounts:", ", ".join(sorted(existing)), file=sys.stderr)
            return 1

        password = getpass.getpass("New password: ")
        if len(password) < MIN_LENGTH:
            print(f"Too short — use at least {MIN_LENGTH} characters.", file=sys.stderr)
            return 1
        if password != getpass.getpass("Confirm: "):
            print("The two entries did not match.", file=sys.stderr)
            return 1

        user.hashed_password = hash_password(password)
        db.commit()
        print(f"Password updated for {email}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
