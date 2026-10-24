# Assessment: Continuous Delivery (CD) to AWS for Geo-Yield-AI

**Document Status:** Architectural Proposal & Engineering Assessment  
**Date:** October 2026  
**Author:** Cloud Engineering & Architecture Team  
**Target Systems:** Frontend (Vue 3 / Vite SPA), Backend API (FastAPI / Uvicorn), Database (Amazon RDS PostgreSQL / PostGIS / pgvector), AWS Services (S3, CloudFront, ECR, EC2 / ECS, IAM, SSM)  
**Target Region:** `eu-central-1` (Europe - Frankfurt) / `eu-south-2` (Europe - Spain)  
**Security Baseline:** Zero Plaintext Secrets (GitHub OIDC & AWS IAM Roles)

---

## 1. Executive Summary & Assessment Overview

**Geo-Yield-AI** has operational Continuous Integration (CI) in `.github/workflows/integrate.yml` (Pytest, ESLint, Prettier, Ruff) and a partial frontend deployment workflow (`deploy-frontend.yml`). However, backend deployment currently relies on an external legacy webhook to Render (`deploy.yml`), while AWS infrastructure (EC2, S3, CloudFront, RDS) is already provisioned or audited in Frankfurt (`eu-central-1`) and Spain (`eu-south-2`).

This assessment defines the engineering blueprint to transition from manual/hybrid deployments to an **automated, secure, and production-grade Continuous Delivery (CD) pipeline to AWS**.

### Current State vs. Target State Comparison

| Architectural Dimension | Current CD State | Target AWS CD Architecture | Strategic Impact |
| :--- | :--- | :--- | :--- |
| **Backend Compute Delivery** | Manual `workflow_dispatch` triggering Render webhook (`deploy.yml`). | Automated build to **Amazon ECR** & deployment to **EC2 via AWS Systems Manager (SSM)** or **ECS Fargate**. | Unifies compute on AWS; supports unbuffered SSE streaming and IAM Instance Profiles. |
| **Frontend Delivery** | Static long-lived IAM keys in `deploy-frontend.yml` syncing to S3 & invalidating CloudFront in `eu-south-2`. | **GitHub Actions OIDC (OpenID Connect)** syncing hashed assets to S3 and invalidating `/index.html` on CloudFront. | Eliminates long-lived AWS keys in GitHub; protects against credential leaks; ensures region parity (`eu-central-1`). |
| **Database Migrations** | Executed manually from local host or bastion (`load_to_db.py`, `alembic upgrade head`). | Automated pre-deployment migration step run inside the VPC via SSM or ephemeral container before API traffic cutover. | Prevents schema divergence and runtime 500 errors on database models. |
| **Secret Management** | Mix of GitHub secrets and manual server `.env` files. | **AWS Secrets Manager / SSM Parameter Store** injected at runtime into containers; zero secrets in Git or CI logs. | Complies with strict security standards; supports automated secret rotation. |
| **Deployment Strategy** | In-place recreation with service downtime. | Zero-downtime rolling container swap (Blue/Green or Nginx upstream reload) with automated rollback on failure. | High availability for end users and active legal assistant / SSE streams. |

---

## 2. End-to-End CD Pipeline Architecture

```
                                 [ Developer Push / Merge ]
                                             |
                                             v
                           +-----------------------------------+
                           |        GitHub Actions CI          |
                           |   (Lint, Format, Unit Tests)      |
                           +-----------------+-----------------+
                                             | (Pass Gate)
                                             v
                         [ GitHub Actions CD (OIDC Assumed Role) ]
                         • Short-lived AWS STS token (No API keys)
                                             |
                     +-----------------------+-----------------------+
                     |                                               |
                     v (Frontend Path)                               v (Backend Path)
        +-------------------------+                     +-------------------------+
        |   Node.js 20 / Vite     |                     |    Docker Multi-Stage   |
        |    npm run build        |                     |     Build API Image     |
        +------------+------------+                     +------------+------------+
                     |                                               |
                     v                                               v
        +-------------------------+                     +-------------------------+
        |  S3 Sync (Cache Headers)|                     | Push to Amazon ECR Repo |
        |  • /assets: immutable   |                     | • Tag: git SHA & latest |
        |  • /index.html: no-cache|                     +------------+------------+
        +------------+------------+                                  |
                     |                                               v
                     v                                  +-------------------------+
        +-------------------------+                     | VPC Migration Gate      |
        | CloudFront Invalidation |                     | Alembic upgrade head    |
        | • Target: /index.html   |                     +------------+------------+
        +-------------------------+                                  |
                                                                     v
                                                        +-------------------------+
                                                        | Deploy Container to EC2 |
                                                        | via AWS SSM (RunCommand)|
                                                        | • Pull ECR image        |
                                                        | • Swap container        |
                                                        | • Health check /ready   |
                                                        +-------------------------+
```

---

## 3. Detailed Component Assessment & Technical Strategy

### 3.1 Backend Deployment: Options & Trade-Off Matrix

The backend is a containerized FastAPI application (`deployment/Dockerfile`) requiring low-latency SSE streaming (`/api/reports/stream`), IAM access to Bedrock (`amazon.titan-embed-text-v2:0`), and private VPC access to PostgreSQL (PostGIS + pgvector).

| Option | Architecture Pattern | Deployment Complexity | Monthly AWS Cost | Zero-Downtime Support | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Option 1: EC2 + SSM (Current Footprint)** | Docker container on existing EC2 `t4g.small` / `t3.micro`, deployed via **AWS Systems Manager (SSM)** Run Command. | **Low** (Builds on current server setup without altering networking). | **~€15 - €18** (Uses existing server) | Yes (Dual-container port swap behind local Nginx). | **Recommended for Phase 1 (Immediate)** |
| **Option 2: AWS ECS Fargate** | Serverless container tasks behind an Application Load Balancer (ALB). | **Medium** (Requires provisioning ALB, Target Group, ECS Cluster/Service). | **~€35 - €45** (ALB baseline ~$20 + Fargate vCPU/RAM) | Native (ECS rolling updates with circuit breaker). | **Recommended for Phase 2 (Scale)** |
| **Option 3: AWS App Runner** | Fully managed container runtime. | **Low** (Direct ECR trigger). | **~€20 - €30** | Native rolling updates. | Not recommended (VPC Connector egress adds latency for DB and SSE tuning is constrained). |

#### Recommended Backend CD Workflow (Option 1 - EC2 via SSM)
1. **Container Build & Push:** GitHub Actions builds `deployment/Dockerfile` targeting ARM64/AMD64 (matching instance architecture) and authenticates to Amazon ECR.
2. **Schema Migration Execution:** Before updating the web server, SSM triggers the migration command inside the VPC using a temporary container:
   ```bash
   docker run --rm --network geoyield_net \
     -e DATABASE_URL="$RDS_DATABASE_URL" \
     ${ECR_REGISTRY}/geoyield-backend:${GITHUB_SHA} \
     alembic -c database/alembic.ini upgrade head
   ```
3. **Rolling Zero-Downtime Container Swap:**
   - Run the new container on an alternate internal port (e.g. `8001`).
   - Poll internal health endpoint `http://127.0.0.1:8001/ready` until HTTP 200 OK.
   - Switch local Nginx upstream to `8001` with `nginx -s reload`.
   - Terminate the old container on `8000`.
4. **Automated Health Verification:** Post-deployment probe checks the public API `/health` and `/ready`.

---

### 3.2 Frontend Deployment: S3 + CloudFront Edge Delivery

The frontend is a Vue 3 / Vite Single Page Application (`frontend/`).

#### Flaws Identified in Current `deploy-frontend.yml`
1. **Security Vulnerability:** Uses long-lived static access keys (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).
2. **Region & Origin Inconsistency:** Uses `s3://geoyield-frontend` in `eu-south-2` with hardcoded distribution `E20TNUC7CKHU1I`, while backend migration target is `eu-central-1`.
3. **Inefficient Invalidation:** Runs wildcard `/*` invalidation on every commit. While covered under the initial 1,000 monthly free paths, this invalidates already content-hashed immutable JS/CSS bundles unnecessarily.
4. **Hardcoded API URL:** `VITE_API_BASE_URL: https://d2yya2azx26rn0.cloudfront.net` is hardcoded in YAML instead of utilizing relative paths `/api` proxied directly by CloudFront (Zero-CORS architecture).

#### Target Frontend CD Standards
- **OIDC Authentication:** Assume temporary role `arn:aws:iam::<ACCOUNT_ID>:role/GitHubActions-Frontend-CD`.
- **Differential Caching Headers during `aws s3 sync`:**
  - **Static Assets (`/assets/*.js`, `/assets/*.css`):** Cache for 1 year (`Cache-Control: public, max-age=31536000, immutable`). Vite hashes filenames on every build.
  - **HTML Entry Point (`index.html`):** No cache (`Cache-Control: public, max-age=0, must-revalidate`).
- **Precision CloudFront Invalidation:** Only invalidate `/index.html` and `/version.json` (sub-second edge purge, zero cost overhead).

---

### 3.3 Security & Zero-Secret Identity Architecture (GitHub OIDC)

To eliminate hardcoded credentials in GitHub repository secrets, AWS IAM will be configured with an **OpenID Connect (OIDC) Identity Provider** for GitHub Actions.

#### IAM OIDC Configuration
- **Provider URL:** `https://token.actions.githubusercontent.com`
- **Audience:** `sts.amazonaws.com`

#### IAM Role Trust Policy (Branch-Restricted)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::192445490421:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:pontia/PJ:ref:refs/heads/*"
        }
      }
    }
  ]
}
```

#### Granular IAM Permissions Policy for GitHub Actions
The CD role requires strictly scoped privileges:
- **ECR:** `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:PutImage`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`.
- **S3:** `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`, `s3:DeleteObject` on `arn:aws:s3:::geoyield-frontend*`.
- **CloudFront:** `cloudfront:CreateInvalidation` on `arn:aws:cloudfront::192445490421:distribution/*`.
- **SSM:** `ssm:SendCommand`, `ssm:GetCommandInvocation` on EC2 instance `i-0ea3a1136e12a6166`.
- **Zero Port 22:** Because deployment is dispatched via SSM over HTTPS (AWS outbound agent), **port 22 (SSH) can be completely removed from `geoyield-firewall`**, dramatically reducing attack surface.

---

### 3.4 Database Migration & Schema Evolution Strategy

Alembic migrations (`database/alembic/versions/`) manage schema state up to `0006_titan_embeddings_dim.py`.

#### Handling Network Isolation
The target RDS instance resides in private DB subnets without public internet access. GitHub runner nodes cannot connect directly to port 5432.

#### The 3-Step Safe Migration Flow in CD:
1. **Pre-flight Check in CI (`integrate.yml`):**
   Run `alembic -c database/alembic.ini check` in CI to guarantee that local model changes match migration revisions and that no multiple heads exist.
2. **Execute Migration in VPC:**
   During CD execution, the SSM agent on the EC2 host (which has security group ingress to RDS port 5432) executes the migration container:
   ```bash
   alembic -c database/alembic.ini upgrade head
   ```
3. **Backward-Compatibility Rule (Expand/Contract):**
   All migrations must be backward-compatible with the currently running API version. Destructive changes (column drops, renames) must be executed in a two-stage deployment:
   - *Deploy 1:* Add new column/table, deploy API that writes to both.
   - *Deploy 2:* Backfill data, deploy API reading from new structure, drop old column.

---

### 3.5 Environments & Branching Strategy

To establish reliable governance across development cycles:

| Environment | Trigger Branch / Event | Target Infrastructure | Deployment Mode | Approvals Required |
| :--- | :--- | :--- | :--- | :--- |
| **Staging / Dev** | Push to `develop` | • S3 Staging Bucket<br>• Staging CloudFront<br>• EC2 Dev Container | Automated continuous deployment | None |
| **Production** | Push to `main` or Tag `v*.*.*` | • Production S3 (`geoyield-frontend`)<br>• Production CloudFront<br>• EC2 Prod Server (`i-0ea3a1136e12a6166`)<br>• Production RDS | Automated with GitHub Environment Gate | 1 Required Reviewer (Tech Lead) |

---

## 4. Proposed Target Workflow Implementations

### 4.1 Backend CD Workflow (`.github/workflows/deploy-backend.yml`)

```yaml
name: Deploy Backend to AWS

on:
  push:
    branches:
      - main
    paths:
      - 'backend/**'
      - 'database/**'
      - 'deployment/Dockerfile'
      - '.github/workflows/deploy-backend.yml'
  workflow_dispatch:

permissions:
  id-token: write   # Required for AWS OIDC authentication
  contents: read

jobs:
  build-and-deploy:
    name: Build ECR & Deploy EC2
    runs-on: ubuntu-latest
    environment: production

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Configure AWS Credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::192445490421:role/GitHubActions-Backend-CD
          aws-region: eu-central-1

      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build, tag, and push Docker image to ECR
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          ECR_REPOSITORY: geoyield-backend
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG -t $ECR_REGISTRY/$ECR_REPOSITORY:latest -f deployment/Dockerfile .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest

      - name: Deploy via AWS Systems Manager (SSM)
        env:
          INSTANCE_ID: i-0ea3a1136e12a6166
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          COMMAND="aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin $ECR_REGISTRY && \
                   docker pull $ECR_REGISTRY/geoyield-backend:$IMAGE_TAG && \
                   docker run --rm --network geoyield_net -e DATABASE_URL=\"\$DATABASE_URL\" $ECR_REGISTRY/geoyield-backend:$IMAGE_TAG alembic -c database/alembic.ini upgrade head && \
                   docker stop geoyield_api || true && \
                   docker rm geoyield_api || true && \
                   docker run -d --name geoyield_api --restart unless-stopped --network geoyield_net -p 8080:8000 --env-file /opt/geoyield/.env $ECR_REGISTRY/geoyield-backend:$IMAGE_TAG"
          
          COMMAND_ID=$(aws ssm send-command \
            --instance-ids "$INSTANCE_ID" \
            --document-name "AWS-RunShellScript" \
            --parameters "commands=[\"$COMMAND\"]" \
            --query "Command.CommandId" \
            --output text)

          aws ssm wait command-executed \
            --command-id "$COMMAND_ID" \
            --instance-id "$INSTANCE_ID"

      - name: Smoke Test Live Health Check
        run: |
          curl --fail --retry 5 --retry-delay 5 https://api.geoyield.es/ready || curl --fail http://3.64.17.221:8080/ready
```

---

### 4.2 Modernized Frontend CD Workflow (`.github/workflows/deploy-frontend.yml`)

```yaml
name: Deploy Frontend to S3 and CloudFront

on:
  push:
    branches:
      - main
    paths:
      - 'frontend/**'
      - '.github/workflows/deploy-frontend.yml'
  workflow_dispatch:

permissions:
  id-token: write   # Required for AWS OIDC authentication
  contents: read

jobs:
  deploy-frontend:
    name: Build & Edge Deploy
    runs-on: ubuntu-latest
    environment: production

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci

      - name: Build frontend for production
        working-directory: frontend
        env:
          VITE_API_BASE_URL: ""  # Empty string utilizes relative CloudFront /api routing (zero CORS)
        run: npm run build

      - name: Configure AWS Credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::192445490421:role/GitHubActions-Frontend-CD
          aws-region: eu-central-1

      - name: Sync Static Assets (Long-term Immutable Cache)
        run: |
          aws s3 sync frontend/dist/assets s3://geoyield-frontend-eu-central-1/assets \
            --cache-control "public, max-age=31536000, immutable" \
            --delete

      - name: Sync HTML & Root Assets (Must Revalidate)
        run: |
          aws s3 sync frontend/dist s3://geoyield-frontend-eu-central-1 \
            --exclude "assets/*" \
            --cache-control "public, max-age=0, must-revalidate" \
            --delete

      - name: Invalidate CloudFront Entry Point
        run: |
          aws cloudfront create-invalidation \
            --distribution-id E20TNUC7CKHU1I \
            --paths "/index.html" "/version.json"
```

---

## 5. Rollback & Disaster Recovery Strategy

| Failure Scenario | Detection Mechanism | Automated / Manual Rollback Procedure | Recovery Time Objective (RTO) |
| :--- | :--- | :--- | :--- |
| **Backend API Startup Failure (Crashloop)** | Post-deploy `/ready` health probe returns non-200. | SSM script captures non-zero exit code and immediately spins back up the previous tagged image (`geoyield-backend:previous`). | **< 60 seconds** |
| **Corrupted Frontend Bundle** | Automated synthetic HTTP request fails to load main JS chunk. | Re-run workflow pointing to the prior commit SHA, or restore S3 version via S3 Versioning, followed by CloudFront invalidation. | **< 3 minutes** |
| **Breaking Database Migration** | `alembic upgrade head` encounters schema constraint violation or timeout. | The pipeline aborts immediately *before* restarting or replacing the API container. Run `alembic downgrade -1` via SSM. | **Immediate (API remains on old schema)** |

---

## 6. Implementation Roadmap

```markdown
- [ ] Phase 1: AWS Identity & Security Baseline (1-2 days)
      - Provision AWS IAM OIDC Provider for GitHub Actions (`token.actions.githubusercontent.com`).
      - Create IAM Roles `GitHubActions-Backend-CD` and `GitHubActions-Frontend-CD` with scoped policies.
      - Remove long-lived AWS IAM User keys from GitHub repository secrets.

- [ ] Phase 2: Registry & Compute CD Setup (2 days)
      - Create Amazon ECR private repository `geoyield-backend` in `eu-central-1` with 10-image lifecycle policy.
      - Attach AWS Systems Manager (SSM) instance profile to EC2 `Geo-Yield-Server` (`i-0ea3a1136e12a6166`).
      - Verify outbound SSM agent connectivity; revoke inbound Port 22 (SSH) from `geoyield-firewall`.

- [ ] Phase 3: Pipeline Migration & Testing (2-3 days)
      - Create `.github/workflows/deploy-backend.yml` and test manual dispatch with tag pinning.
      - Refactor `.github/workflows/deploy-frontend.yml` to use OIDC, differential caching headers, and precise invalidations.
      - Conduct end-to-end rehearsal with a sample Alembic migration and verify `/ready` health checks.
      - Deprecate legacy Render deployment hook (`deploy.yml`).
```
