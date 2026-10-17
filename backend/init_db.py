
"""One-time schema initialization for a fresh Care Plus database.

Run only against the dedicated Care Plus PostgreSQL database.
This script creates missing tables and does not seed demo records.
"""

from app.db import models  # noqa: F401
from app.db.database import Base, engine


def main() -> None:
    print("Initializing Care Plus database schema...")
    Base.metadata.create_all(bind=engine)
    print("Schema initialization completed.")


if __name__ == "__main__":
    main()
