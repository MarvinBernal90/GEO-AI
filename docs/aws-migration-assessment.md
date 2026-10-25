# Geo-Yield-AI — AWS migration assessment

**Status:** Target architecture. **Date:** October 2026. **Region:** `eu-central-1` (Frankfurt).

## Current vs target

| Layer | Today | Target |
| --- | --- | --- |
| Frontend | S3 + CloudFront, deployed by `deploy-frontend.yml` | Same, with OAC and SPA fallback |
| API | Docker on EC2 `i-0ea3a1136e12a6166`, deployed over SSM by `deploy.yml`, IAM instance profile for Bedrock and CloudWatch | Same host, behind Nginx with SSE buffering disabled |
| Database | `postgis` container (Postgres 18 + PostGIS + pgvector) in the same Compose stack on the EC2 host | Amazon RDS for PostgreSQL 18 in private subnets |
| Cache | `redis` container in the same stack | Same |
| AI | Bedrock: Titan V2 embeddings, Rerank 1.0, Nova 2 Lite | Same |
| Logs | Docker `awslogs` driver to `/geoyield/api` | Same, 30-day retention |

The goal of the migration is to separate persistent data from compute so the API host can be replaced without touching data. Only the database moves; the rest is already on AWS.

```
Users ──> CloudFront ──(OAC)──> S3 (Vue build)
              └── /api/* ──> EC2 (Nginx -> FastAPI in Docker, instance profile)
                                   ├──> RDS PostgreSQL 18 (PostGIS + pgvector, private subnet)
                                   ├──> Bedrock (Titan V2, Rerank, Nova)
                                   └──> CloudWatch Logs (/geoyield/*)
```

## Components

### Database (RDS)
- RDS PostgreSQL 18 supports `postgis` and `vector`. Create both extensions before restoring.
- `legal_chunks.embedding` is `vector(1024)` with an HNSW cosine index (migrations `0003`, `0006`).
- Private DB subnets in two AZs, `PubliclyAccessible = false`, port 5432 open only to the backend security group.
- Data moves with `pg_dump -Fc --no-owner --no-acl` and `pg_restore`; the full runbook is [aws-rds-migration.md](aws-rds-migration.md).

### API host (EC2)
- `t4g.small` (Graviton, ARM64) is enough for the MVP; build the image for the instance architecture.
- Nginx must not buffer Server-Sent Events (`/api/reports/stream`, `/api`, `/api/assistant`):

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8080;      # compose publishes the API on 8080
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;                    # critical for SSE
    proxy_cache off;
    proxy_read_timeout 300s;
}
```

- No stored secrets: the instance profile (`aws/bedrock/bedrock-policy.json`) grants Bedrock inference and rerank, and CloudWatch Logs on `/geoyield/*`.
- Set `TRUSTED_PROXY_HOPS` to the number of proxies in front of the API.

### Frontend (S3 + CloudFront)
- Private bucket, read access only for CloudFront via Origin Access Control.
- Custom error responses `403`/`404` → `/index.html` with `200`, because the router uses history mode (`/metrics` must work on refresh).
- Optional cache behaviours: `/*` → S3 (cached), `/api/*` → EC2 (no cache, forward all headers). One domain means no CORS preflights.

## Network and security

| Group | Rule | Purpose |
| --- | --- | --- |
| `sg-backend` | Inbound 80/443 from the internet or CloudFront | API traffic and SSE |
| `sg-backend` | SSH only from an admin IP, or none if SSM is used | Administration |
| `sg-database` | Inbound 5432 only from `sg-backend` | Database access |

Public subnets host the EC2 instance; database subnets are private with no internet route. Use `sslmode=verify-full` in the RDS `DATABASE_URL`.

## Cost (monthly, on-demand, order of magnitude)

| Service | Sizing | Cost |
| --- | --- | --- |
| RDS PostgreSQL | `db.t4g.small`, Single-AZ, 20 GB gp3 | ~€31 |
| EC2 | `t4g.small`, 20 GB gp3 | ~€14.50 |
| Elastic IP | 1 in-use IPv4 | ~€3.40 |
| S3 | < 1 GB | < €0.50 |
| CloudFront | Within the free tier | €0 |
| Bedrock + CloudWatch | Pay per token and ingestion | ~€3-5 |
| **Total** | | **~€52-55** |

Savings plans and reserved instances can cut compute and database cost by roughly 30%.

## Roadmap

1. **Network and IAM.** VPC with two public and two private subnets, the two security groups, the instance profile.
2. **Database.** Launch RDS, create the extensions, `pg_dump` / `pg_restore`, then `alembic -c database/alembic.ini current` must report `0009`.
3. **Backend.** Point `DATABASE_URL` at RDS, remove the `postgis` service from the deployed stack, add Nginx.
4. **Frontend.** Build with `npm run build`, sync to S3, configure OAC and the SPA fallback.
5. **Verification and cutover.** Check `/health` and `/ready`, `/api/districts`, `/api/competitors` and a streamed report, then switch DNS.

## Rollback

Rehearse the full restore on staging first. The local database stays untouched during migration, so before any write reaches RDS rollback is just pointing `DATABASE_URL` back. Once production writes land on RDS, freeze writes and snapshot before any maintenance. Roll back if pgvector or PostGIS behave differently on RDS, or if SSE streaming fails through the proxy.
