"""Sessions SQLAlchemy ; l'isolation tenant repose sur PostgreSQL RLS (app.tenant_id par transaction)."""
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: Optional[str]) -> Iterator[Session]:
    """Ouvre une transaction dont toutes les requêtes sont filtrées par RLS sur tenant_id."""
    with SessionLocal() as s:
        with s.begin():
            # set_config(..., true) = SET LOCAL : valable pour la transaction courante uniquement
            s.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id or ""})
            yield s
