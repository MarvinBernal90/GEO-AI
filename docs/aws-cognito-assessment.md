# Architectural Assessment: Amazon Cognito User Management for Geo-Yield-AI

**Date:** October 2026  
**Status:** Proposal / Assessment  
**Author:** AI Engineering & Architecture Team  
**Target Systems:** Backend (FastAPI), Frontend (Vue 3 / Vite), Database (PostgreSQL / PostGIS), Agent Memory (LangGraph / PostgresSaver)

---

## 1. Executive Summary

Adding **Amazon Cognito** is a natural and high-value architectural evolution for **Geo-Yield-AI**. The platform already utilizes AWS managed services—**Amazon Bedrock** (Titan Text Embeddings V2, Nova Lite) for intelligence and **Amazon CloudWatch** for observability.

Incorporating Cognito completes the AWS cloud footprint by providing an enterprise-grade, serverless identity layer without taking on the operational and compliance liabilities of storing password hashes, building reset flows, or managing custom JWT signing keys.

| Dimension | Assessment | Notes |
| :--- | :--- | :--- |
| **Architectural Alignment** | **High** | Natively integrates with Bedrock, CloudWatch, and future AWS compute (ECS/Fargate/App Runner). |
| **Implementation Complexity** | **Low to Moderate** | Stateless JWT validation in FastAPI; standard SPA integration via `@aws-amplify/auth` in Vue 3. |
| **Operational Cost** | **$0 / month** | Free tier includes **50,000 Monthly Active Users (MAU)** permanently for standard sign-in. |
| **Core Business Value** | **Multi-Tenancy** | Transforms anonymous sessions into isolated, secure user workspaces with Role-Based Access Control (RBAC). |

---

## 2. Key Capabilities & Architectural Value

### 2.1 User-Isolated Conversational Memory (`backend/ia/chat.py`)
- **Current State:** The ReAct chat agent (`chat.py`) uses PostgreSQL checkpointing (`PostgresSaver`) keyed by arbitrary thread identifiers (e.g., `"1"`, `"3"`). Multiple users or sessions risk clobbering each other's memory.
- **With Cognito:** Each authenticated user is issued a verified, immutable UUID (`sub` claim). Chat threads in Postgres can be scoped to the authenticated user:
  ```python
  thread_id = f"{current_user['sub']}:{conversation_id}"
  ```
  This ensures complete multi-tenant privacy and session segmentation.

### 2.2 Role-Based Access Control (RBAC)
Using **Cognito User Pool Groups** (e.g., `admin`, `premium_investor`, `analyst`), the backend can gate sensitive administrative endpoints:
- Triggering ETL imports (`/api/etl/*`).
- Uploading and re-indexing municipal legal corpus PDFs.
- Viewing internal diagnostic telemetry and logs (`/api/logs`).

### 2.3 Turnkey Security & Compliance
- Automated email verification and password reset workflows.
- Optional Multi-Factor Authentication (MFA / TOTP) and adaptive threat protection.
- Refresh token rotation and token revocation without maintaining custom session tables.

---

## 3. System Architecture & Authentication Flow

```
┌─────────────────────────────────┐
│  Vue 3 Client (localhost:5173)  │
└──────────────┬──────────────────┘
               │ 1. Sign In (Amplify Auth / Hosted UI)
               ▼
┌─────────────────────────────────┐
│     AWS Cognito User Pool       │
│  - User Directory               │
│  - Issues ID & Access JWTs      │
└──────────────┬──────────────────┘
               │ 2. Returns JWT tokens (Access + ID Token)
               ▼
┌─────────────────────────────────┐
│  Vue 3 Client (localhost:5173)  │
└──────────────┬──────────────────┘
               │ 3. API Request: 'Authorization: Bearer <Access_JWT>'
               ▼
┌─────────────────────────────────┐
│    FastAPI (localhost:8000)     │
│  - Validates signature vs JWKS  │
│  - Extracts 'sub', 'groups'     │
│  - Injects user dependency      │
└──────────────┬──────────────────┘
               │ 4. Scopes queries by user 'sub'
               ▼
┌─────────────────────────────────┐
│  PostgreSQL / PostgresSaver     │
│  Thread ID: "{sub}:{conv_id}"   │
└─────────────────────────────────┘
```

---

## 4. Technical Component Design

### 4.1 AWS Cognito Setup
1. **User Pool**:
   - Primary sign-in attribute: Email address.
   - Self-service sign-up enabled with email verification codes.
   - Strong password policy (min 8 chars, numbers, symbols, uppercase).
2. **App Client**:
   - Client Type: **Public client / SPA** (**NO client secret**).
   - OAuth Flows: **Authorization Code grant with PKCE** (for Hosted UI) or `ALLOW_USER_SRP_AUTH` (for embedded Vue forms).
   - Allowed Callback URLs:
     - Local: `http://localhost:5173/callback`
     - Production: `https://your-domain.com/callback`
   - Allowed Sign-out URLs: `http://localhost:5173`, `https://your-domain.com`

### 4.2 Backend Layer (FastAPI)
- **Stateless Validation via JWKS**:
  FastAPI fetches and caches Cognito's public JSON Web Key Set from:
  `https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/jwks.json`
  Every protected request is validated statelessly in memory with **0 network round-trips to AWS**.
- **Dependency Injection (`backend/api/deps.py`)**:
  ```python
  from fastapi import Depends, HTTPException, status
  from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
  import jwt
  from jwt import PyJWKClient

  security = HTTPBearer(auto_error=False)

  COGNITO_REGION = os.getenv("AWS_REGION", "eu-central-1")
  COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
  COGNITO_APP_CLIENT_ID = os.getenv("COGNITO_APP_CLIENT_ID", "")
  AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"

  jwks_url = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json"
  jwks_client = PyJWKClient(jwks_url) if COGNITO_USER_POOL_ID else None

  async def get_current_user(
      credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
  ) -> dict:
      if not AUTH_ENABLED:
          # Development / test bypass mode
          return {"sub": "dev-user-000", "email": "dev@geoyield.local", "groups": ["admin"]}

      if not credentials:
          raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization token")

      token = credentials.credentials
      try:
          signing_key = jwks_client.get_signing_key_from_jwt(token)
          payload = jwt.decode(
              token,
              signing_key.key,
              algorithms=["RS256"],
              issuer=f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}",
              audience=COGNITO_APP_CLIENT_ID,
              options={"verify_exp": True},
          )
          return {
              "sub": payload["sub"],
              "email": payload.get("email"),
              "username": payload.get("username", payload.get("cognito:username")),
              "groups": payload.get("cognito:groups", []),
          }
      except Exception as err:
          raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {err}")
  ```

### 4.3 Frontend Layer (Vue 3 / Vite)
- Package: `@aws-amplify/auth`
- Configuration in `src/main.js`:
  ```javascript
  import { Amplify } from 'aws-amplify';

  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID,
        userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID,
      }
    }
  });
  ```
- Network attachment in `src/services/api.js`:
  Tokens are retrieved from session and injected automatically as `Authorization: Bearer <token>` on all outgoing fetch calls.

---

## 5. Implementation Roadmap

| Phase | Scope | Deliverables | Est. Effort |
| :--- | :--- | :--- | :--- |
| **Phase 1: AWS Setup** | Cloud Infrastructure | User Pool, App Client (no secret), groups (`admin`, `user`), test users. | 1 – 2 hrs |
| **Phase 2: Backend Auth** | API Security | `get_current_user` in `deps.py`, RBAC guard `require_group`, test fixture bypass. | 2 – 4 hrs |
| **Phase 3: Chat Scoping** | Agent Multi-tenancy | Scope `thread_id` in `backend/ia/chat.py` with `current_user.sub`. | 1 – 2 hrs |
| **Phase 4: Frontend UI** | Client Integration | Auth service wrapper, Login/Register modal or Hosted UI redirect, token attach in `api.js`. | 3 – 5 hrs |
| **Phase 5: Automated Tests** | Quality & CI/CD | Unit tests for token verification, group authorization, and dependency overrides. | 2 – 3 hrs |

---

## 6. Critical Security Gotchas & Guidelines

1. **No Client Secret on SPAs:**
   A public client (browser/Vue app) must **never** have a client secret configured in Cognito. Browsers cannot keep secrets confidential, and token requests will fail with secret hash errors.
2. **Access Token vs ID Token:**
   - Authorize backend API requests with the **Access Token** (validates scopes, client_id, and group membership).
   - Use the **ID Token** on the frontend strictly to display user profile details (`email`, `name`, avatar).
3. **Local Development Resilience:**
   Always include an `AUTH_ENABLED=false` bypass mechanism in `backend/api/deps.py`. This ensures developer onboarding remains frictionless and automated test suites (`pytest`) run without network dependencies or AWS credentials.
4. **Token Storage:**
   For standard SPAs, in-memory or secure cookie storage is preferred over `localStorage` to mitigate token-stealing XSS risks.

---

## 7. Conclusion

Integrating Amazon Cognito into Geo-Yield-AI is straightforward, incurs zero additional AWS costs under the generous Free Tier, and addresses the critical architectural gap of user isolation in the ReAct chat engine.
