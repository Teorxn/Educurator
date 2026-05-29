"""
Script para crear el usuario admin inicial.
Uso: python seed.py
"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.config import settings
from app.models.models import User, UserRole
from app.utils.security import hash_password

engine = create_async_engine(settings.DATABASE_URL)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

SEED_USERS = [
    {"email": "admin@educurator.dev", "password": "admin1234", "role": UserRole.admin},
    {"email": "instructor@educurator.dev", "password": "instructor1234", "role": UserRole.instructor},
]


async def main():
    from sqlalchemy import select

    async with SessionLocal() as db:
        for u in SEED_USERS:
            exists = (await db.execute(select(User).where(User.email == u["email"]))).scalar_one_or_none()
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
        await db.commit()
    print("Seed done.")


asyncio.run(main())
