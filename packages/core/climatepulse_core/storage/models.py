"""SQLAlchemy 2.0 async declarative models for Climate Pulse metadata tables.

Only the three metadata tables are modelled here:
- sources: data source registry (ARPA, ECMWF, ...)
- variables: WMO variable catalog (air_temperature, wind_speed, ...)
- stations: station registry (per-source station catalog)

The `observations` and `gridded_observations` hypertables are intentionally
NOT modelled in the ORM. The hot ingest path uses asyncpg
`copy_records_to_table` for ~3x performance vs. ORM inserts. The hypertable
DDL is managed via Alembic `op.execute()` raw SQL in the initial migration.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Double,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM metadata models."""

    pass


class SourceRow(Base):
    """ORM model for the `sources` metadata table.

    Stores data source registry entries. `source_id` is the human-readable
    identifier (e.g. 'arpa_emilia', 'ecmwf_open'); `id` is the surrogate
    SMALLSERIAL primary key referenced by `stations.source_id` FK.
    """

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(
        SmallInteger,
        Identity(always=True),
        primary_key=True,
    )
    source_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
        comment="Human-readable source identifier, e.g. 'arpa_emilia'",
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    license: Mapped[str] = mapped_column(String, nullable=False)
    attribution: Mapped[str] = mapped_column(String, nullable=False)
    terms_url: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    stations: Mapped[list["StationRow"]] = relationship(
        "StationRow", back_populates="source", lazy="noload"
    )


class VariableRow(Base):
    """ORM model for the `variables` metadata table.

    Stores the WMO variable catalog. `wmo_code` is the canonical variable name
    (e.g. 'air_temperature'); `bufr_code` is the optional WMO BUFR Table B code
    (e.g. 'B12101'); `unit_si` is the SI unit string.
    """

    __tablename__ = "variables"

    id: Mapped[int] = mapped_column(
        SmallInteger,
        Identity(always=True),
        primary_key=True,
    )
    wmo_code: Mapped[str] = mapped_column(
        String,
        nullable=False,
        unique=True,
        comment="Canonical WMO variable code, e.g. 'air_temperature'",
    )
    bufr_code: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment="WMO BUFR Table B code, e.g. 'B12101'; None for derived variables",
    )
    unit_si: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="SI unit string, e.g. 'K', 'm s-1', 'Pa'",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class StationRow(Base):
    """ORM model for the `stations` metadata table.

    Links to the `sources` table via `source_id` FK. The combination of
    (source_id, external_id) is unique — different sources may reuse the same
    `external_id` string but they refer to distinct physical stations.
    """

    __tablename__ = "stations"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_stations_source_external"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    source_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("sources.id", ondelete="RESTRICT"),
        nullable=False,
        comment="FK to sources.id (surrogate SMALLSERIAL key)",
    )
    external_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Source-assigned station identifier",
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lon: Mapped[float] = mapped_column(Double, nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="Station elevation in metres above sea level",
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="Arbitrary source-specific metadata as JSON",
    )

    # Relationship back to source
    source: Mapped["SourceRow"] = relationship(
        "SourceRow", back_populates="stations", lazy="noload"
    )
