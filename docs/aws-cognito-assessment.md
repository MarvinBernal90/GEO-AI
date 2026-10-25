# Amazon Cognito for user management — assessment

**Status:** Proposal (not implemented). **Date:** October 2026.

## Current state

- `POST /api/login` checks that a username exists in the `users` table. There is no password or token, and any client can claim any username.
- Users are preloaded (the four team members' GitHub names plus `administrador`) by `database/load_users.py`.
- Conversations are keyed by `thread_id = "<username>:<n>"` in the LangGraph `PostgresSaver` checkpoints, and `login` lists a user's threads by username prefix. Text history goes to `chat_history/<thread_id>.txt`.
- Nothing authenticates the API itself: `/api/assistant`, `/api/gethistory`, `/api/metrics/*` and the rest are open, and the ETL webhooks rely on a shared secret.

## Proposal

Use **Cognito** (the project already uses Bedrock and CloudWatch) for sign-in and JWT issuance. Free tier covers 50,000 MAU.

| Benefit | How |
| --- | --- |
| Verified identity | Each user gets an immutable `sub`. Threads become `"{sub}:{conversation_id}"`, so conversations cannot be read by claiming another name |
| Protected endpoints | The backend validates the access token and can restrict `/api/assistant`, `/api/gethistory` and `/api/metrics/*` |
| Roles | Cognito groups (`admin`, `user`) can gate ETL triggers, corpus uploads and metrics |
| Account features | Email verification, password reset, optional MFA, refresh-token revocation, with no password storage in our DB |

## Design

```
Vue SPA --sign in--> Cognito User Pool --JWT--> SPA --Authorization: Bearer--> FastAPI
                                                     (validates against JWKS, extracts sub and groups)
```

- **User pool.** Email sign-in, self-service sign-up with email verification, strong password policy.
- **App client.** Public SPA client with **no client secret**; authorization code with PKCE (Hosted UI) or SRP for embedded forms. Callback URLs for `http://localhost:5173` and production.
- **Backend.** A `get_current_user` dependency in `backend/api/deps.py` fetches the pool's JWKS (`https://cognito-idp.<region>.amazonaws.com/<pool-id>/.well-known/jwks.json`), verifies RS256 signature, issuer, audience and expiry locally, and returns `sub`, `email` and `cognito:groups`. A `require_group("admin")` guard protects admin routes. Variables: `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `AUTH_ENABLED`.
- **Frontend.** `aws-amplify` Auth configured in `main.js` (`VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_CLIENT_ID`); `services/api.js` adds the bearer token to every call, including the SSE `fetch`es.
- **Chat scoping.** `thread_id` is built from the token's `sub`, never from a client-supplied name.

## Guidelines

1. **No client secret** on a browser app.
2. **Access token** for API authorization; use the ID token only to display profile data.
3. **`AUTH_ENABLED=false` bypass** for local development and `pytest`, returning a fixed dev user, so onboarding and CI need no AWS access.
4. Prefer in-memory or secure-cookie token storage over `localStorage` to limit XSS exposure.
5. Migrating existing threads (`<username>:<n>`) to `sub`-based ids needs a one-off rename of checkpoints and history files.

## Roadmap

| Phase | Scope | Effort |
| --- | --- | --- |
| 1. AWS setup | User pool, app client, groups, test users | 1-2 h |
| 2. Backend auth | `get_current_user`, `require_group`, test bypass | 2-4 h |
| 3. Chat scoping | `thread_id` from `sub`; migrate existing threads | 1-2 h |
| 4. Frontend | Auth wrapper, login UI or Hosted UI redirect, token on every call | 3-5 h |
| 5. Tests | Token verification, group checks, dependency overrides | 2-3 h |
