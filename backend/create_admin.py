
from getpass import getpass

from dotenv import load_dotenv

# Load the existing backend environment before importing app settings.
load_dotenv("backend/.env")

from sqlalchemy import select

from app.api.auth import password_hash
from app.db.database import Base, SessionLocal, engine
from app.db.models import User


def main():
    Base.metadata.create_all(bind=engine)

    full_name = input("Administrator full name: ").strip()
    email = input("Administrator email: ").strip().lower()
    password = getpass("Administrator password (minimum 12 characters): ")
    confirm = getpass("Confirm password: ")

    if not full_name or not email:
        raise SystemExit("Name and email are required.")

    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters.")

    if password != confirm:
        raise SystemExit("Passwords do not match.")

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            raise SystemExit(
                "This email already exists. No administrator was created."
            )

        admin = User(
            full_name=full_name,
            email=email,
            password_hash=password_hash.hash(password),
            role="ADMIN",
            is_active=True,
        )
        db.add(admin)
        db.commit()

    print(f"Administrator created for {email}.")


if __name__ == "__main__":
    main()



