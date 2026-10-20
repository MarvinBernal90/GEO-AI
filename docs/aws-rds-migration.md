# Migrating Geo-Yield-AI to AWS RDS for PostgreSQL

This runbook moves the local PostgreSQL database to **Amazon RDS for PostgreSQL** using a logical backup (`pg_dump`) and restore (`pg_restore`). It keeps the existing application connection contract: the API, ETL jobs, and Alembic all use `DATABASE_URL`.

The database currently requires both **PostGIS** (geography queries) and **pgvector** (384-dimensional legal embeddings and an HNSW index). Do not start the migration until the selected RDS PostgreSQL engine version supports compatible versions of both extensions. AWS extension support is version-specific; check the [RDS PostgreSQL extensions documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Extensions.html) and verify on the actual target instance as described below.

## 1. Provision the RDS target

Create an RDS PostgreSQL instance in the application VPC. Prefer the same PostgreSQL major version as the source (currently PostgreSQL 18); if RDS does not offer a compatible engine/extension combination, rehearse a major-version migration separately before cutover.

Recommended baseline:

- Keep the instance private; do not enable public access. Allow inbound TCP 5432 only from the application security group. For a migration from a laptop, use VPN/bastion access rather than opening the database to the internet.
- Enable encryption at rest, automated backups, and deletion protection for production. Choose Multi-AZ based on the service's availability requirement.
- Create a database named `geoyield`. Keep the RDS master credentials out of the application configuration; use a dedicated runtime database user and a separate migration/administration credential where practical.
- Use a PostgreSQL 18-or-newer `pg_dump`/`pg_restore` client. A client older than the source server cannot dump it.

Connect to the new database with an administrative account and verify that both extensions are available before copying data:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name IN ('postgis', 'vector')
ORDER BY name;
```

Both rows must be returned. Compare the available versions with the source (`SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis', 'vector');`). If an extension is unavailable or incompatible, stop and select a supported RDS engine version before proceeding.

## 2. Rehearse a backup and restore

Install PostgreSQL client tools version 18 or newer on a machine that can reach both databases. Put the connection strings in a secure local secret mechanism or temporary environment variables; do not commit them to `.env.example`, scripts, or shell history. The `pg_dump` connection string uses the libpq form `postgresql://...`, not SQLAlchemy's `postgresql+psycopg2://...` form.

The source is the local `geoyield` database. For a host-side connection to the current Compose database, use `localhost` and the published Postgres port. The target URL uses the RDS endpoint and TLS; use `sslmode=verify-full` with the current AWS RDS CA bundle where available.

```bash
pg_dump --format=custom --no-owner --no-acl \
  --dbname "$SOURCE_PGURL" \
  --file geoyield.dump

pg_restore --list geoyield.dump
```

Restore into a **new, empty** RDS database. `pg_restore` may take a while for the legal corpus and its vector index; capture its output and do not switch application traffic until it exits successfully:

```bash
pg_restore --verbose --exit-on-error --no-owner --no-acl \
  --dbname "$TARGET_PGURL" \
  geoyield.dump
```

Run the restore as an RDS administrative/migration account capable of creating the project schema and extensions. The archive includes the Alembic version and extension declarations; RDS must support those extensions. `--no-owner --no-acl` avoids trying to recreate local database roles and grants that do not exist in RDS. Before production, grant the runtime database role only the permissions it needs; use a migration/owner role for Alembic DDL.

After restoring, connect to RDS and verify:

```sql
SELECT version_num FROM alembic_version;
SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis', 'vector');
SELECT PostGIS_Full_Version();
SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector AS vector_distance;
SELECT count(*) FROM competitors;
SELECT count(*) FROM legal_chunks;
```

Compare row counts with the source. Confirm the Alembic revision is `0005` (the current repository head) and exercise representative spatial and legal-search API requests against the restored database.

## 3. Cut over

Do a rehearsal first and record its duration. For the production cutover:

1. Put the API into maintenance mode or stop it, and pause ETL/load jobs so the source no longer receives writes.
2. Take a final `pg_dump` and restore that archive to a fresh/clean RDS database using the commands above. Do not restore over a partially restored target.
3. Update the application's secret configuration with the RDS SQLAlchemy URL, for example `postgresql+psycopg2://...@<rds-endpoint>:5432/geoyield?sslmode=verify-full&sslrootcert=<path-to-rds-ca-bundle>`. Ensure the CA bundle is present in the runtime environment. Keep `DB_HOST_OVERRIDE` and `DB_PORT_OVERRIDE` unset/empty; they are only for local development routing.
4. Run `alembic -c database/alembic.ini current` with the migration credential and the target `DATABASE_URL`. It should report `0005`. Apply `upgrade head` only if a newer migration is intentionally part of this release.
5. Start one API instance, check `/health` and `/ready`, then test a spatial endpoint and a legal/RAG query. Resume normal API capacity and ETL only after these checks pass.
6. Keep the original database intact and unwritten through the agreed verification window. Take/confirm an RDS snapshot and automated backup before closing the migration window.

The running application does not need a code change: `backend/db/connection.py` already reads `DATABASE_URL`, and Alembic uses that same resolver. For a local API process, set the new URL in the untracked root `.env`. For a deployed service, set it in that service's secret manager/configuration and redeploy or restart. The current Compose file is for local development and still starts its local PostGIS container; it is not an RDS production deployment definition.

## 4. Rollback

Before any production writes reach RDS, rollback is simply to stop the new API and restore the old `DATABASE_URL` to the still-preserved source database. Once writes have reached RDS, switching back would lose those writes; stop traffic and reconcile/replicate the new writes first, or fix forward on RDS. Do not treat the original database as a current rollback target after it has become stale.

## Notes

- This logical migration copies one database, not PostgreSQL cluster roles or server-level settings. Recreate required roles, grants, parameter-group settings, and operational alarms in AWS separately.
- `pg_dump`/`pg_restore` requires a write pause for a consistent final cutover. If the database is too large for the maintenance window, use AWS Database Migration Service (DMS) for an initial load plus change-data capture, while still provisioning and validating the RDS extensions/schema separately.
- Never expose the RDS endpoint publicly just to make a one-time migration easier, and never put database credentials in source control.
