"""
Script para crear el usuario admin inicial.
Uso: python seed.py
"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import User, UserRole
from app.utils.security import hash_password

# Usar psycopg2 en vez de asyncpg (evita problemas en Windows)
db_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
engine = create_engine(db_url)

SEED_USERS = [
    {"email": "admin@educurator.dev", "password": "admin1234", "role": UserRole.admin},
    {"email": "instructor@educurator.dev", "password": "instructor1234", "role": UserRole.instructor},
]


def main():
    with Session(engine) as db:
        for u in SEED_USERS:
            exists = db.execute(select(User).where(User.email == u["email"])).scalar_one_or_none()
            if exists:
                print(f"  skip  {u['email']} (already exists)")
                continue
            user = User(
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                role=u["role"],
            )
            db.add(user)
            print(f"  added {u['email']} ({u['role'].value})")
        db.commit()
    print("Seed done.")


if __name__ == "__main__":
    main()
