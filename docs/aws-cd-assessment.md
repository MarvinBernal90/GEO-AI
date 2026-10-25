# Continuous delivery to AWS — assessment

**Status:** Proposal. **Date:** October 2026. **Region:** `eu-central-1`.

## Current state

| Area | What `.github/workflows/` does today |
| --- | --- |
| CI (`integrate.yml`) | On pull requests: unit tests with coverage, Ruff, ESLint, Prettier and a frontend build. `check-branch-name.yml` enforces branch naming |
| Backend (`deploy.yml`) | On push to `develop` (paths `backend/`, `database/`, `deployment/`) or manually: SSM Run Command on EC2 `i-0ea3a1136e12a6166` that does `git reset --hard origin/develop`, syncs processed data from S3, runs `docker compose up -d --build`, then `alembic upgrade head` and a `/health` check |
| Frontend (`deploy-frontend.yml`) | On push to `develop` (path `frontend/`) or manually: `npm ci`, build with `VITE_APP_VERSION` = commit SHA, `aws s3 sync --delete` to `geoyield-frontend-192445490421-eu-central-1`, invalidate `/*` on CloudFront |
| Credentials | Both deploy workflows use long-lived `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` GitHub secrets |

Weaknesses:

1. **Static AWS keys** in GitHub secrets.
2. **Builds on the production host.** `docker compose up --build` compiles on EC2, with no versioned image to roll back to.
3. **Migrations run after the new container starts**, so a failing migration leaves a running API on a mismatched schema.
4. **No post-deploy rollback.** A failed health check fails the job but does not restore the previous version.
5. **Wildcard invalidation** (`/*`) on every frontend deploy, and one cache policy for hashed and unhashed files.
6. **Hardcoded API URL** (`VITE_API_BASE_URL`) in the workflow instead of a relative `/api` path through CloudFront.

## Proposed changes

### 1. GitHub OIDC instead of static keys
Create an IAM OIDC provider for `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`) and two roles, `GitHubActions-Backend-CD` and `GitHubActions-Frontend-CD`, with trust restricted to this repository and its deploy branches (`sub` = `repo:<org>/<repo>:ref:refs/heads/...`). Workflows then set `permissions: id-token: write` and use `aws-actions/configure-aws-credentials` with `role-to-assume`. Scope the permissions:

- Backend: ECR push, and `ssm:SendCommand` / `ssm:GetCommandInvocation` on the instance.
- Frontend: `s3:PutObject/GetObject/ListBucket/DeleteObject` on the frontend bucket and `cloudfront:CreateInvalidation`.

Then delete the static keys from the repository secrets.

### 2. Build once, deploy an image
Build `deployment/Dockerfile` in CI for the instance architecture and push to a private ECR repository (`geoyield-backend`, tagged with the commit SHA, 10-image lifecycle). The host pulls the tag instead of building. Rolling back means running the previous tag.

### 3. Safer migrations and swap
- In CI, run `alembic -c database/alembic.ini check` to catch missing revisions and multiple heads.
- During deploy, run `alembic upgrade head` in a one-off container **before** swapping the API, and abort on failure.
- Keep migrations backward compatible with the running version (expand, then contract): add columns first, drop or rename in a later release.
- Start the new container on a second port, wait for `/ready`, switch the Nginx upstream, then stop the old one. If `/ready` fails, keep the old container.

### 4. Frontend caching
Sync `assets/` with `Cache-Control: public, max-age=31536000, immutable` (Vite hashes file names) and everything else with `max-age=0, must-revalidate`. Invalidate only `/index.html`. Build with an empty `VITE_API_BASE_URL` once CloudFront proxies `/api/*`.

### 5. Secrets and hardening
Move runtime secrets from the host `.env` to SSM Parameter Store or Secrets Manager. With SSM as the deploy channel, SSH (port 22) can be closed.

## Options for the backend runtime

| Option | Fit | Cost / month |
| --- | --- | --- |
| **EC2 + SSM + ECR** (today's host) | Smallest change, keeps SSE tuning and the instance profile. Recommended now | ~€15-18 |
| ECS Fargate behind an ALB | Native rolling updates; more to provision. Consider when scaling | ~€35-45 |
| App Runner | Simple, but VPC egress adds latency to DB access and SSE tuning is limited. Not recommended | ~€20-30 |

## Environments

| Environment | Trigger | Approval |
| --- | --- | --- |
| Development | Push to `develop` (as today) | None |
| Production | Push to `main` or a `v*.*.*` tag, using a GitHub Environment | One required reviewer |

## Rollback

| Failure | Detection | Action |
| --- | --- | --- |
| API does not start | `/ready` non-200 after deploy | Re-run the previous image tag |
| Bad frontend bundle | Smoke check fails | Re-run the workflow on the previous commit, or restore the S3 object version, then invalidate `/index.html` |
| Migration fails | `alembic upgrade head` errors | Pipeline stops before the swap; the old API keeps running on the old schema |

## Roadmap

1. **Identity (1-2 days):** OIDC provider and roles; remove static keys.
2. **Registry and host (2 days):** ECR repository, SSM-capable instance profile on the EC2 host, close SSH.
3. **Pipelines (2-3 days):** image-based `deploy.yml`, hardened `deploy-frontend.yml`, a rehearsal with a sample migration.
