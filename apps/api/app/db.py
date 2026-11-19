"""Sessions SQLAlchemy ; l'isolation tenant repose sur PostgreSQL RLS (app.tenant_id par transaction)."""
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, event, text
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


# Évaluations faites juste avant la validation, dans la même transaction (une notification n'existe que si la modification est
# réellement enregistrée) : couverture des marques ajoutées manuellement ; caducité des propositions de remplacement en attente.
@event.listens_for(SessionLocal, "after_flush")
def _watch_mark(session, _flush_context):
    from .integration_watch import mark
    from .replacements import mark as mark_replacements
    mark(session)
    mark_replacements(session)


@event.listens_for(SessionLocal, "before_commit")
def _watch_evaluate(session):
    if session.info.get("coverage_dirty") or session.info.get("replacement_dirty") or session.new or session.dirty or session.deleted:
        session.flush()
        from .replacements import evaluate as evaluate_replacements
        evaluate_replacements(session)  # d'abord : une proposition caduque est close avant le calcul de couverture
        from .integration_watch import evaluate
        evaluate(session)
