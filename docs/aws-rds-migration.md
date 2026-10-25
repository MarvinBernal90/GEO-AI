# Migrating the database to Amazon RDS for PostgreSQL

Runbook to move the Compose database to **RDS** with `pg_dump` / `pg_restore`. The app needs no code change: the API, ETL and Alembic all read `DATABASE_URL`. Context and target design: [aws-migration-assessment.md](aws-migration-assessment.md).

The database needs **PostGIS** (geography queries) and **pgvector** (1024-dimension legal embeddings with an HNSW index). Do not start until the chosen RDS engine version offers both ([RDS extension versions](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Extensions.html)).

## 1. Provision the target

- Use the same major version as the source (PostgreSQL 18). If RDS lacks a compatible engine/extension combination, rehearse a major-version migration separately.
- Keep it private (no public access), port 5432 only from the application security group. From a laptop, use a VPN or bastion.
- Enable encryption at rest, automated backups and deletion protection. Create a database named `geoyield`. Use a separate runtime user and a migration/admin user.
- Use `pg_dump` / `pg_restore` version 18 or newer.

Connect as admin and check both extensions exist:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions WHERE name IN ('postgis', 'vector') ORDER BY name;
```

Both rows must appear. Compare versions with the source (`SELECT extname, extversion FROM pg_extension ...`).

## 2. Rehearse backup and restore

Connection strings use the libpq form `postgresql://...` (not `postgresql+psycopg2://`). Keep them in environment variables, never in files or shell history. For the Compose source use `localhost` and the published port (`POSTGRES_HOST_PORT`).

```bash
pg_dump --format=custom --no-owner --no-acl --dbname "$SOURCE_PGURL" --file geoyield.dump
pg_restore --list geoyield.dump

# into a new, empty RDS database, as an admin account (use sslmode=verify-full)
pg_restore --verbose --exit-on-error --no-owner --no-acl --dbname "$TARGET_PGURL" geoyield.dump
```

The restore of the legal corpus and its vector index can take a while; do not switch traffic until it exits successfully. Then verify:

```sql
SELECT version_num FROM alembic_version;       -- expect 0009 (current repository head)
SELECT extname, extversion FROM pg_extension WHERE extname IN ('postgis', 'vector');
SELECT count(*) FROM competitors;
SELECT count(*) FROM legal_chunks;
```

Compare row counts with the source and run a spatial request and a legal-search request against the restored database.

## 3. Cut over

1. Stop the API (or enter maintenance mode) and pause ETL jobs.
2. Take a final dump and restore it into a fresh RDS database. Never restore over a partial one.
3. Set the new URL in the service's secrets: `postgresql+psycopg2://...@<rds-endpoint>:5432/geoyield?sslmode=verify-full&sslrootcert=<ca-bundle>`. Keep `DB_HOST_OVERRIDE` and `DB_PORT_OVERRIDE` empty (they are for local development only).
4. Run `alembic -c database/alembic.ini current` against the target; it should report `0009`. Run `upgrade head` only if a newer migration ships with this release.
5. Start one API instance, check `/health` and `/ready`, then a spatial endpoint and a RAG query, and only then restore full capacity and ETL.
6. Keep the original database intact and unwritten for the agreed verification window, and confirm an RDS snapshot before closing it.

`docker-compose.yml` still starts a local `postgis` container; for a deployment that uses RDS, drop that service from the stack.

## 4. Rollback

Before any production write reaches RDS, stop the new API and restore the old `DATABASE_URL`. After writes reach RDS, switching back loses them: reconcile first or fix forward. A stale source database is no longer a valid rollback target.

## Notes

- A logical dump copies one database, not cluster roles or server settings. Recreate roles, grants, parameter groups and alarms separately.
- `pg_dump` needs a write pause for a consistent cutover. For large databases, use AWS DMS (initial load plus change capture) and validate extensions and schema separately.
- Never expose the RDS endpoint publicly for a one-time migration, and never commit credentials.
