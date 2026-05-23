"""SQLAlchemy 2.0 ORM models for Climate Pulse metadata tables.

Only the metadata tables (sources, variables, stations) are modelled in the ORM.
The `observations` and `gridded_observations` hypertables are NOT modelled here
because the hot ingest path uses asyncpg COPY (copy_records_to_table) for
performance, and the TimescaleDB hypertable DDL is managed exclusively via
Alembic op.execute() calls in the migrations.
"""

from climatepulse_core.storage.models import (
    Base,
    SourceRow,
    StationRow,
    VariableRow,
)

__all__ = [
    "Base",
    "SourceRow",
    "VariableRow",
    "StationRow",
]
