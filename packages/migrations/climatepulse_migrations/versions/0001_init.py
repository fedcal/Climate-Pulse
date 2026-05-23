"""Initial schema: metadata + two hypertables (D-23) + CAGGs + compression + retention.
Refresh < compress < retention verified.

Policy ordering verification (Pitfall #3 — refresh_lag < compress_after < retention_after):
  observations:        end_offset 1h  < compress 7d  < retention 5y    ✓
  obs_daily:           end_offset 1d  < retention 20y                   ✓
  gridded_observations: end_offset 6h  < compress 7d  < retention 90d  ✓
  gridded_daily:       end_offset 1d  < retention 20y                   ✓

Phase boundary comment:
  STO-03 mandates hierarchical CAGGs in Phase 1. Both daily CAGGs (obs_daily
  on obs_hourly and gridded_daily on gridded_hourly) are created here per D-23
  dual-hypertable parity. They are NOT deferred to Phase 2.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the full Climate Pulse schema in the correct dependency order.

    Execution order (sequence matters — Pitfall #3 requires policy ordering
    refresh_lag < compress_after < retention_after):

    1.  TimescaleDB extension
    2.  Metadata tables: sources, variables, stations
    3.  Hypertable base tables: observations, gridded_observations
    4.  create_hypertable() calls (STO-01)
    5.  Additional indexes on hypertables
    6.  Compression settings + policies (STO-04) — 7d after hypertable creation
    7.  Retention policies on raw hypertables (STO-05)
    8.  CAGG obs_hourly (raw → hourly, STO-03)
    9.  CAGG obs_daily (obs_hourly → daily, STO-03 hierarchical)
    10. Retention on obs_daily (20y default, STO-05)
    11. CAGG gridded_hourly (raw → 6h, STO-03 grid tier)
    12. CAGG gridded_daily (gridded_hourly → daily, STO-03 hierarchical)
    13. Retention on gridded_daily (20y default, STO-05)
    """
    # -------------------------------------------------------------------------
    # 1. TimescaleDB extension
    # -------------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    # -------------------------------------------------------------------------
    # 2. Metadata tables
    # -------------------------------------------------------------------------
    op.create_table(
        "sources",
        sa.Column(
            "id",
            sa.SmallInteger(),
            sa.Identity(always=True),
            nullable=False,
            comment="Surrogate primary key (SMALLSERIAL)",
        ),
        sa.Column(
            "source_id",
            sa.String(),
            nullable=False,
            comment="Human-readable source identifier, e.g. 'arpa_emilia'",
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("license", sa.String(), nullable=False),
        sa.Column("attribution", sa.String(), nullable=False),
        sa.Column("terms_url", sa.String(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_sources_source_id"),
    )

    op.create_table(
        "variables",
        sa.Column(
            "id",
            sa.SmallInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column(
            "wmo_code",
            sa.String(),
            nullable=False,
            comment="Canonical WMO variable code, e.g. 'air_temperature'",
        ),
        sa.Column(
            "bufr_code",
            sa.String(),
            nullable=True,
            comment="WMO BUFR Table B code, e.g. 'B12101'; None for derived variables",
        ),
        sa.Column(
            "unit_si",
            sa.String(),
            nullable=False,
            comment="SI unit string, e.g. 'K', 'm s-1', 'Pa'",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wmo_code", name="uq_variables_wmo_code"),
    )

    op.create_table(
        "stations",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.SmallInteger(),
            nullable=False,
            comment="FK to sources.id",
        ),
        sa.Column(
            "external_id",
            sa.String(),
            nullable=False,
            comment="Source-assigned station identifier",
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lon", sa.Double(), nullable=False),
        sa.Column(
            "elevation_m",
            sa.REAL(),
            nullable=True,
            comment="Station elevation in metres above sea level",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Arbitrary source-specific metadata as JSON",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="RESTRICT",
            name="fk_stations_source_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "external_id",
            name="uq_stations_source_external",
        ),
    )

    # -------------------------------------------------------------------------
    # 3. Hypertable base tables
    # -------------------------------------------------------------------------
    # observations: station-based (ARPAE) — STO-01
    # PK includes observed_at (time column) to satisfy Pitfall #2 and STO-01.
    op.create_table(
        "observations",
        sa.Column(
            "observed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Observation timestamp (UTC). Part of PK per STO-01.",
        ),
        sa.Column(
            "station_id",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "variable_id",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "value",
            sa.Double(),
            nullable=False,
        ),
        sa.Column(
            "qc_flag",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
            comment="QcFlag enum value: 0=GOOD, 1=MISSING, 2=OUT_OF_RANGE, "
                    "3=SCHEMA_VIOLATION, 4=STALE_SNAPSHOT",
        ),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Server-side ingestion timestamp (T-02-05: writer must not override)",
        ),
        sa.ForeignKeyConstraint(
            ["station_id"],
            ["stations.id"],
            ondelete="RESTRICT",
            name="fk_observations_station_id",
        ),
        sa.ForeignKeyConstraint(
            ["variable_id"],
            ["variables.id"],
            ondelete="RESTRICT",
            name="fk_observations_variable_id",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="RESTRICT",
            name="fk_observations_source_id",
        ),
        # PK includes time column (Pitfall #2 + STO-01)
        sa.PrimaryKeyConstraint(
            "station_id",
            "variable_id",
            "observed_at",
            "source_id",
            name="pk_observations",
        ),
    )

    # gridded_observations: grid-based (ECMWF) — D-23 second hypertable
    # PK includes valid_at (time column) to satisfy Pitfall #2.
    op.create_table(
        "gridded_observations",
        sa.Column(
            "valid_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Valid time = init_time + step_h hours. Part of PK.",
        ),
        sa.Column(
            "init_time",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            comment="Forecast cycle time (00Z, 06Z, 12Z, 18Z)",
        ),
        sa.Column(
            "step_h",
            sa.SmallInteger(),
            nullable=False,
            comment="Forecast step in hours",
        ),
        sa.Column(
            "lat_idx",
            sa.SmallInteger(),
            nullable=False,
            comment="Grid row index (0.25° grid resolution)",
        ),
        sa.Column(
            "lon_idx",
            sa.SmallInteger(),
            nullable=False,
            comment="Grid column index (0.25° grid resolution)",
        ),
        sa.Column(
            "lat",
            sa.REAL(),
            nullable=False,
            comment="Latitude in decimal degrees",
        ),
        sa.Column(
            "lon",
            sa.REAL(),
            nullable=False,
            comment="Longitude in decimal degrees",
        ),
        sa.Column(
            "variable_id",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "value",
            sa.Double(),
            nullable=False,
        ),
        sa.Column(
            "qc_flag",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
            comment="QcFlag enum value: 0=GOOD, 1=MISSING, 2=OUT_OF_RANGE, "
                    "3=SCHEMA_VIOLATION, 4=STALE_SNAPSHOT",
        ),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Server-side ingestion timestamp (T-02-05: writer must not override)",
        ),
        sa.ForeignKeyConstraint(
            ["variable_id"],
            ["variables.id"],
            ondelete="RESTRICT",
            name="fk_gridded_variable_id",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="RESTRICT",
            name="fk_gridded_source_id",
        ),
        # PK includes valid_at (time column) per Pitfall #2
        sa.PrimaryKeyConstraint(
            "lat_idx",
            "lon_idx",
            "variable_id",
            "valid_at",
            "source_id",
            name="pk_gridded_observations",
        ),
    )

    # -------------------------------------------------------------------------
    # 4. create_hypertable() calls — STO-01 (Pitfall #1: chunk_time_interval)
    # -------------------------------------------------------------------------
    # observations: 7-day chunks (station data, moderate cardinality)
    op.execute(
        "SELECT create_hypertable("
        "    'observations', 'observed_at',"
        "    chunk_time_interval => INTERVAL '7 days',"
        "    if_not_exists => TRUE"
        ")"
    )

    # gridded_observations: 1-day chunks (ECMWF EU grid ~41k points/cycle —
    # higher cardinality than station data; see RESEARCH.md line 536)
    op.execute(
        "SELECT create_hypertable("
        "    'gridded_observations', 'valid_at',"
        "    chunk_time_interval => INTERVAL '1 day',"
        "    if_not_exists => TRUE"
        ")"
    )

    # -------------------------------------------------------------------------
    # 5. Additional indexes on hypertables
    # -------------------------------------------------------------------------
    op.execute(
        "CREATE INDEX obs_var_time ON observations (variable_id, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX obs_station_time ON observations (station_id, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX gridded_var_time"
        " ON gridded_observations (variable_id, valid_at DESC)"
    )
    op.execute(
        "CREATE INDEX gridded_coord_time"
        " ON gridded_observations (lat_idx, lon_idx, valid_at DESC)"
    )

    # -------------------------------------------------------------------------
    # 6. Compression settings + policies — STO-04
    # Policy ordering verified: compress_after(7d) > refresh_end_offset(1h/6h)
    # -------------------------------------------------------------------------
    # observations compression
    op.execute(
        "ALTER TABLE observations SET ("
        "    timescaledb.compress,"
        "    timescaledb.compress_segmentby = 'station_id, variable_id',"
        "    timescaledb.compress_orderby = 'observed_at DESC, source_id'"
        ")"
    )
    op.execute(
        "SELECT add_compression_policy('observations', INTERVAL '7 days')"
    )

    # gridded_observations compression
    op.execute(
        "ALTER TABLE gridded_observations SET ("
        "    timescaledb.compress,"
        "    timescaledb.compress_segmentby = 'lat_idx, lon_idx, variable_id',"
        "    timescaledb.compress_orderby = 'valid_at DESC, source_id'"
        ")"
    )
    op.execute(
        "SELECT add_compression_policy('gridded_observations', INTERVAL '7 days')"
    )

    # -------------------------------------------------------------------------
    # 7. Retention policies on raw hypertables — STO-05
    # Policy ordering verified: retention_after > compress_after(7d)
    # -------------------------------------------------------------------------
    # observations: 5y raw retention (STO-05 default)
    # 5y >> 7d compress ✓
    op.execute(
        "SELECT add_retention_policy('observations', INTERVAL '5 years')"
    )

    # gridded_observations: 90d raw retention (ECMWF data is large)
    # 90d >> 7d compress ✓
    op.execute(
        "SELECT add_retention_policy('gridded_observations', INTERVAL '90 days')"
    )

    # -------------------------------------------------------------------------
    # 8. CAGG obs_hourly (raw observations → hourly buckets) — STO-03
    # Buckets raw `observations.observed_at` into 1-hour intervals.
    # Policy: start_offset 3d, end_offset 1h, schedule 15min
    # end_offset(1h) << compress_after(7d) << retention(5y) ✓
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW obs_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(INTERVAL '1 hour', observed_at) AS bucket,
            station_id,
            variable_id,
            source_id,
            avg(value)   AS avg_value,
            min(value)   AS min_value,
            max(value)   AS max_value,
            count(*)     AS sample_count
        FROM observations
        GROUP BY 1, 2, 3, 4
        WITH NO DATA
        """
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy("
        "    'obs_hourly',"
        "    start_offset  => INTERVAL '3 days',"
        "    end_offset    => INTERVAL '1 hour',"
        "    schedule_interval => INTERVAL '15 minutes'"
        ")"
        # Policy ordering: refresh_lag(1h) < compress_after(7d) < retention(5y) ✓
    )

    # -------------------------------------------------------------------------
    # 9. CAGG obs_daily (obs_hourly → daily buckets) — STO-03 hierarchical
    # CRITICAL: buckets obs_hourly.bucket NOT raw observations.observed_at.
    # This is the hierarchical CAGG pattern required by STO-03.
    # Policy: start_offset 7d, end_offset 1d, schedule 1h
    # end_offset(1d) << retention(20y) ✓
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW obs_daily
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(INTERVAL '1 day', bucket) AS day_bucket,
            station_id,
            variable_id,
            source_id,
            avg(avg_value)       AS avg_value,
            min(min_value)       AS min_value,
            max(max_value)       AS max_value,
            sum(sample_count)    AS sample_count
        FROM obs_hourly
        GROUP BY 1, 2, 3, 4
        WITH NO DATA
        """
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy("
        "    'obs_daily',"
        "    start_offset  => INTERVAL '7 days',"
        "    end_offset    => INTERVAL '1 day',"
        "    schedule_interval => INTERVAL '1 hour'"
        ")"
        # Policy ordering: refresh_lag(1d) < retention(20y) ✓
    )

    # -------------------------------------------------------------------------
    # 10. Retention on obs_daily — STO-05 default 20y for aggregates
    # -------------------------------------------------------------------------
    op.execute(
        "SELECT add_retention_policy('obs_daily', INTERVAL '20 years')"
    )

    # -------------------------------------------------------------------------
    # 11. CAGG gridded_hourly (raw gridded_observations → 6h buckets) — STO-03
    # 6-hour bucket matches ECMWF IFS cycle cadence (00Z/06Z/12Z/18Z).
    # Policy: start_offset 3d, end_offset 6h, schedule 1h
    # end_offset(6h) << compress_after(7d) << retention(90d) ✓
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW gridded_hourly
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(INTERVAL '6 hours', valid_at) AS bucket,
            lat_idx,
            lon_idx,
            variable_id,
            source_id,
            avg(value)   AS avg_value,
            min(value)   AS min_value,
            max(value)   AS max_value,
            count(*)     AS sample_count
        FROM gridded_observations
        GROUP BY 1, 2, 3, 4, 5
        WITH NO DATA
        """
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy("
        "    'gridded_hourly',"
        "    start_offset  => INTERVAL '3 days',"
        "    end_offset    => INTERVAL '6 hours',"
        "    schedule_interval => INTERVAL '1 hour'"
        ")"
        # Policy ordering: refresh_lag(6h) < compress_after(7d) < retention(90d) ✓
    )

    # -------------------------------------------------------------------------
    # 12. CAGG gridded_daily (gridded_hourly → daily buckets) — STO-03 hierarchical
    # CRITICAL: buckets gridded_hourly.bucket NOT raw gridded_observations.valid_at.
    # Symmetric to obs_daily per D-23 dual-hypertable parity.
    # Policy: start_offset 7d, end_offset 1d, schedule 1h
    # end_offset(1d) << retention(20y) ✓
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW gridded_daily
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket(INTERVAL '1 day', bucket) AS day_bucket,
            lat_idx,
            lon_idx,
            variable_id,
            source_id,
            avg(avg_value)       AS avg_value,
            min(min_value)       AS min_value,
            max(max_value)       AS max_value,
            sum(sample_count)    AS sample_count
        FROM gridded_hourly
        GROUP BY 1, 2, 3, 4, 5
        WITH NO DATA
        """
    )
    op.execute(
        "SELECT add_continuous_aggregate_policy("
        "    'gridded_daily',"
        "    start_offset  => INTERVAL '7 days',"
        "    end_offset    => INTERVAL '1 day',"
        "    schedule_interval => INTERVAL '1 hour'"
        ")"
        # Policy ordering: refresh_lag(1d) < retention(20y) ✓
    )

    # -------------------------------------------------------------------------
    # 13. Retention on gridded_daily — STO-05 default 20y for aggregates
    # -------------------------------------------------------------------------
    op.execute(
        "SELECT add_retention_policy('gridded_daily', INTERVAL '20 years')"
    )


def downgrade() -> None:
    """Drop all schema objects in reverse dependency order.

    CAGGs depend on their source tables/views → drop CAGGs before base tables.
    CASCADE handles policy cleanup automatically when hypertable is dropped.
    Children before parents for CAGG hierarchy:
      gridded_daily (depends on gridded_hourly) → gridded_hourly (depends on gridded_obs)
      obs_daily (depends on obs_hourly) → obs_hourly (depends on observations)
    """
    # Drop hierarchical CAGGs first (children before parents)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS gridded_daily CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS obs_daily CASCADE")
    # Drop base CAGGs
    op.execute("DROP MATERIALIZED VIEW IF EXISTS gridded_hourly CASCADE")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS obs_hourly CASCADE")
    # Drop hypertables (CASCADE removes compression + retention policies)
    op.drop_table("gridded_observations")
    op.drop_table("observations")
    # Drop metadata tables (FK order: stations depends on sources)
    op.drop_table("stations")
    op.drop_table("variables")
    op.drop_table("sources")
