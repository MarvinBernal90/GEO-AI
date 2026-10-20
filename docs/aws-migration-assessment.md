# Geo-Yield-AI — AWS Cloud Migration Assessment

**Document Status:** Approved Architecture  
**Target Region:** `eu-central-1` (Frankfurt) / `eu-west-1` (Ireland)  
**Date:** October 2026  
**Stack Overview:** Amazon RDS for PostgreSQL (PostGIS + pgvector), Amazon EC2 (FastAPI), Amazon S3 + CloudFront (Vue 3 SPA), Amazon Bedrock (Titan V2 & Rerank)

---

## 1. Executive Summary & Migration Objectives

**Geo-Yield-AI** unifies spatial sociodemographic analytics with an artificial intelligence legal assistant (RAG) specialized in Barcelona municipal urban planning (*Pla General Metropolità - PGM*). The system currently operates locally orchestrated via Docker Compose.

This assessment formulates the production engineering strategy to migrate the application into a highly available, secure, and cost-efficient environment in **Amazon Web Services (AWS)**.

### Core Architecture Pillars
- **Decoupled Architecture:** Persistent spatial/vector data is managed by **Amazon RDS for PostgreSQL**; compute and Server-Sent Events (SSE) streaming run on an **Amazon EC2 Graviton3** instance; static frontend assets are delivered via **Amazon S3 and CloudFront** edge caching.
- **Zero Plaintext Secrets:** The backend runs with an **IAM Instance Profile**, enabling passwordless, auto-rotating STS credential authentication for Amazon Bedrock and CloudWatch Logs.
- **Unified Origin / Zero CORS:** CloudFront edge routing proxies `/api/*` requests directly to the EC2 backend while serving static files from S3, completely eliminating browser cross-origin resource sharing (CORS) friction.

---

## 2. End-to-End AWS Target Architecture

```
                                [ Users / Browsers ]
                                          |
                        +-----------------+-----------------+
                        | (HTTPS: 443)                      | (API / SSE: 443)
                        v                                   v
           [ Amazon CloudFront (CDN) ]          [ Amazon EC2 (FastAPI) ]
                        | (OAC / Private)             |   • Reverse Proxy: Nginx
                        v                             |   • App: Docker (python:3.12-slim)
           [ Amazon S3 (Static Assets) ]              |   • IAM Instance Profile
                • Vue 3 / Vite dist                   |
                                                      +---------------+---------------+
                                                      | (Port 5432)   | (SigV4 SDK)   | (Logs)
                                                      v               v               v
                                               [ Amazon RDS ]     [ Bedrock ]   [ CloudWatch ]
                                               Postgres 18        Titan V2      /geoyield/*
                                               PostGIS + pgvector (Embeddings)
                                               (Private Subnet)
```

### Architectural Layer Specifications

| Layer | AWS Service | Specification / Configuration | Operational Responsibilities |
| :--- | :--- | :--- | :--- |
| **Edge / CDN** | **Amazon CloudFront** | HTTPS (443), TLS 1.3, Origin Access Control (OAC), SPA Fallback (`403/404` &rarr; `/index.html` 200 OK) | Global SSL termination, edge caching, static asset delivery, and unified `/api/*` reverse proxying. |
| **Frontend** | **Amazon S3** | Standard Private Bucket with *Block Public Access* enabled; read access granted solely to CloudFront OAC. | Hosts compiled Vue 3 / Vite static assets (HTML, vanilla JS, CSS, SVG icons). Zero server maintenance. |
| **Backend API** | **Amazon EC2** | `t4g.small` (Graviton3, 2 vCPU, 2 GB RAM). Containerized via `deployment/Dockerfile`. Nginx reverse proxy. | FastAPI orchestration, geocoding endpoints, PGM legal retriever, and SSE streaming with buffering disabled. |
| **Database** | **Amazon RDS for PostgreSQL** | PostgreSQL 18 (e.g. 18.6), `db.t4g.small`, 20–50 GB gp3 storage. Extensions: `postgis` + `vector` (pgvector). | Stores census data, commercial competitors, spatial polygons, and 1024-dimensional legal chunk vectors. |
| **AI Services** | **Amazon Bedrock** | Embeddings: `amazon.titan-embed-text-v2:0` (1024d)<br/>Rerank: `amazon.rerank-v1:0` (`eu-central-1`) | Serverless vector embeddings and cross-encoder reranking invoked via Boto3 / SigV4 authentication. |
| **Observability**| **Amazon CloudWatch**| Log group `/geoyield/*`, 30-day retention policy | Centralized structured JSON application and audit logging. |

---

## 3. Component Deep Dive

### 3.1 Relational & Spatial Database (Amazon RDS for PostgreSQL)
1. **Engine & Extension Compatibility:**
   - RDS PostgreSQL 18 natively supports both **`postgis`** (3.x) and **`vector`** (pgvector).
   - Before schema restore, connect with an administrative account and initialize:
     ```sql
     CREATE EXTENSION IF NOT EXISTS postgis;
     CREATE EXTENSION IF NOT EXISTS vector;
     ```
2. **Vector Space Alignment (1024 Dimensions):**
   - Corresponds to Alembic revision `0006_titan_embeddings_dim.py`.
   - The `legal_chunks.embedding` column is typed as `vector(1024)` with an HNSW cosine index:
     ```sql
     CREATE INDEX idx_legal_chunks_embedding ON legal_chunks 
     USING hnsw (embedding vector_cosine_ops);
     ```
3. **Network Isolation:**
   - Placed strictly in private DB subnets across 2 Availability Zones (`PubliclyAccessible = false`).
   - Inbound TCP port 5432 is restricted exclusively to the EC2 security group (`sg-backend`).
4. **Data Migration Runbook:**
   - Logical export from the local Compose container:
     ```bash
     pg_dump --format=custom --no-owner --no-acl --dbname "$SOURCE_PGURL" --file geoyield.dump
     ```
   - Restore into RDS:
     ```bash
     pg_restore --verbose --exit-on-error --no-owner --no-acl --dbname "$RDS_PGURL" geoyield.dump
     ```

### 3.2 Backend API & Streaming Server (Amazon EC2)
1. **Compute Sizing (AWS Graviton3):**
   - AWS `t4g.small` (ARM64) delivers ~20% higher performance per euro for Python asynchronous workloads and spatial arithmetic compared to x86 equivalents.
2. **Reverse Proxy Configuration (SSE Optimization):**
   - The backend uses Server-Sent Events for streaming reports (`/api/reports/stream`) and interactive chat (`/api/chat/informe/stream`).
   - Nginx must disable proxy buffering to avoid holding streaming chunks:
     ```nginx
     location /api/ {
         proxy_pass http://127.0.0.1:8000;
         proxy_http_version 1.1;
         proxy_set_header Connection "";
         proxy_set_header Host $host;
         proxy_set_header X-Real-IP $remote_addr;
         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
         proxy_set_header X-Forwarded-Proto $scheme;

         # Critical for Server-Sent Events (SSE)
         proxy_buffering off;
         proxy_cache off;
         proxy_read_timeout 300s;
     }
     ```
3. **IAM Instance Profile (Zero Plaintext Secrets):**
   - Role attached with permissions:
     - `bedrock:InvokeModel` (Resource: `arn:aws:bedrock:*:*:foundation-model/amazon.titan-embed-text-v2:0`)
     - `bedrock-agent-runtime:Rerank` (Resource: `arn:aws:bedrock:*:*:foundation-model/amazon.rerank-v1:0`)
     - `logs:CreateLogStream`, `logs:PutLogEvents` (Resource: `arn:aws:logs:*:*:log-group:/geoyield/*`)

### 3.3 Frontend Single-Page Application (Amazon S3 + CloudFront)
1. **Static Build Delivery:**
   - Compiled via `npm run build` inside `frontend/` into optimized vanilla HTML/JS/CSS assets (`dist/`).
   - S3 bucket remains private with all public ACLs and bucket policies blocked.
2. **CloudFront with Origin Access Control (OAC):**
   - Secures S3 so assets can only be retrieved through CloudFront.
3. **SPA HTML5 History Routing:**
   - Because Vue Router uses client-side history navigation, deep links return HTTP 403/404 from S3 if refreshed directly.
   - CloudFront Custom Error Response configured:
     - **HTTP Error Code:** `403` and `404`
     - **Response Page Path:** `/index.html`
     - **HTTP Response Code:** `200`
4. **Unified Domain Architecture:**
   - CloudFront can configure two cache behaviors:
     - Default `/*` &rarr; S3 Origin (Cached static assets)
     - `/api/*` &rarr; EC2 Origin (No-cache, forward all headers and cookies)
   - Eliminates CORS preflight requests completely.

---

## 4. Networking, Security & Access Matrix

### VPC Subnet Layout

| Subnet Group | Type | AZ Placement | Internet Access | Hosted Components |
| :--- | :--- | :--- | :--- | :--- |
| **Public Subnets** | Public | `eu-central-1a`, `eu-central-1b` | Direct via Internet Gateway | EC2 Backend (with Elastic IP) |
| **Database Subnets** | Private | `eu-central-1a`, `eu-central-1b` | Isolated (No IGW / No NAT) | RDS PostgreSQL Multi-AZ Subnet Group |

### Security Group Rules Matrix

| Security Group | Direction | Protocol | Port Range | Source / Destination | Purpose |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`sg-backend`** (EC2) | Inbound | TCP | `80`, `443` | `0.0.0.0/0` (or CloudFront IP range) | HTTP/HTTPS web traffic and SSE streaming. |
| | Inbound | TCP | `22` | Admin Bastion / Corporate IP | Administrative SSH (or use AWS Systems Manager). |
| | Outbound | All | All | `0.0.0.0/0` | Outbound to RDS (5432), Bedrock, and Internet APIs. |
| **`sg-database`** (RDS) | Inbound | TCP | `5432` | **`sg-backend` (Security Group ID)** | Dedicated database queries from backend API. Zero public access. |
| | Outbound | None | - | - | Private database does not initiate outbound connections. |

---

## 5. Cost Analysis & Financial Projection (`eu-central-1`)

*Estimates based on official AWS EU (Frankfurt) commercial rates as of late 2026 for a production MVP.*

| AWS Service | Sizing / Instance Class | Pricing Metric | Est. Monthly Cost (EUR) |
| :--- | :--- | :--- | :--- |
| **Amazon RDS PostgreSQL** | `db.t4g.small` (2 vCPU, 2 GB RAM, Single-AZ) | ~$0.0416/hr + 20 GB gp3 ($0.115/GB) | **~ €31.00** |
| **Amazon EC2 Backend** | `t4g.small` (2 vCPU, 2 GB RAM, 20 GB gp3 root) | ~$0.0168/hr + 20 GB gp3 ($0.08/GB) | **~ €14.50** |
| **Elastic IP Address** | 1 In-use IPv4 Address assigned to EC2 | $0.005/hr standard in-use charge | **~ €3.40** |
| **Amazon S3 Storage** | Static frontend build (< 1 GB, standard calls) | Storage + GET/PUT requests | **< €0.50** |
| **Amazon CloudFront** | Edge caching & SSL termination | Covered under 1 TB/mo Always Free Tier | **€0.00** (Free Tier) |
| **Bedrock & CloudWatch** | Titan V2 embeddings + CloudWatch log ingestion | Pay-per-token ($0.00002/1k) + storage | **~ €3.00 – €5.00** |
| **TOTAL ESTIMATED MONTHLY SPEND** | **Production MVP Baseline** | **On-Demand Rates** | **~ €52.40 – €55.00 / month** |

### Cost Optimization Strategies
- **AWS Compute Savings Plans:** Committing to a 1-year or 3-year term for EC2 reduces compute costs by up to 34%.
- **RDS Reserved Instances:** 1-year No-Upfront reservation saves ~30% on database hourly costs.
- **Free Tier Eligibility:** New AWS accounts receive 750 hours/month of `t4g.small` trial for the first 3 months.

---

## 6. Step-by-Step Migration Roadmap & Cutover Plan

```markdown
- [ ] Phase 1: AWS Foundation & Networking
      - Provision custom VPC across 2 AZs (2 Public subnets, 2 Private subnets).
      - Create security groups (`sg-backend` and `sg-database`).
      - Configure IAM Instance Profile with Bedrock and CloudWatch policies.

- [ ] Phase 2: Database Provisioning & Schema Restoration
      - Launch RDS PostgreSQL 18 in private subnets with parameter group.
      - Connect as admin and execute `CREATE EXTENSION postgis; CREATE EXTENSION vector;`.
      - Export local DB: `pg_dump -Fc --no-owner --no-acl -d geoyield -f geoyield.dump`.
      - Restore to RDS: `pg_restore -v --exit-on-error -d geoyield geoyield.dump`.
      - Run Alembic verification: `alembic -c database/alembic.ini current` (must confirm revision `0006`).

- [ ] Phase 3: Backend EC2 Configuration
      - Launch EC2 `t4g.small` instance with IAM Instance Profile.
      - Install Docker / Docker Compose or configure systemd service.
      - Populate production `.env` with RDS `DATABASE_URL` (enforcing `sslmode=verify-full`).
      - Set `AWS_REGION=eu-central-1` and `EMBEDDINGS_MODEL=amazon.titan-embed-text-v2:0`.
      - Configure Nginx reverse proxy with SSE streaming (`proxy_buffering off;`).

- [ ] Phase 4: Frontend Delivery (S3 + CloudFront)
      - Configure `VITE_API_BASE_URL` in `frontend/.env.production`.
      - Build production assets: `npm run build` in `frontend/`.
      - Sync to private S3 bucket: `aws s3 sync dist/ s3://<bucket-name>`.
      - Deploy CloudFront distribution with Origin Access Control (OAC) and SPA 403/404 error redirection.

- [ ] Phase 5: Verification & Cutover
      - Verify `/health` and `/ready` endpoints.
      - Test spatial query execution (`/api/districts`, `/api/competitors`).
      - Test Bedrock Titan V2 embeddings & streaming legal generation (`/api/reports/stream`).
      - Update domain DNS records (Route 53) to point to CloudFront and EC2.
```

---

## 7. Rollback & Disaster Recovery Strategy

1. **Zero-Loss Rehearsal:**
   - Execute a complete end-to-end dry-run of the database restore and application launch using staging endpoints prior to cutover day.
2. **Rollback Trigger Conditions:**
   - Incompatibility with pgvector indexing or PostGIS spatial queries on RDS.
   - Failure of the backend to establish low-latency streaming connections through the reverse proxy.
3. **Rollback Execution:**
   - Since the local database remains intact and unchanged during migration, rollback simply entails redirecting application traffic back to the source environment.
   - Once production writes begin on RDS, freeze writes and take an immediate RDS Snapshot before undertaking any maintenance.
