from alembic import context
from sqlalchemy import create_engine

from app.config import settings
from app.models import Base

url = settings.migration_database_url or settings.database_url
with create_engine(url).connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
    conn.commit()
