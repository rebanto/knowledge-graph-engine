# 20 — User Auth & Per-User Storage: Implementation Guide

Status: **planned — this document is the implementation spec.**
Audience: the coding agent implementing it (Codex). It is self-contained; read
AGENTS.md first for overall architecture.

---

## 0. Decisions (already made — do not re-litigate)

| Decision | Choice | Why |
|---|---|---|
| Auth provider | **Self-hosted JWT in FastAPI** — not Cognito | The free AWS deployment target is the existing docker-compose stack on a single EC2 instance (free tier / signup credits). Cognito adds AWS lock-in, breaks local dev parity, and buys nothing at this scale. Self-hosted auth runs identically on the laptop and on EC2. This supersedes the "Cognito" row in the Phase 7 table of AGENTS.md — update that table as part of this work. |
| Token transport | **HttpOnly cookies** (access + refresh), with `Authorization: Bearer` also accepted | The frontend streams via `EventSource` (`/api/question/stream`, `/api/research/deep/stream`), which **cannot set headers**. Same-origin cookies flow automatically on SSE. Bearer support keeps programmatic/MCP clients possible. |
| Password hashing | **argon2** via `argon2-cffi` | Modern default; passlib is unmaintained. |
| JWT library | **PyJWT** (`pyjwt`), HS256, secret from `AUTH_SECRET_KEY` env | No asymmetric keys needed for a single-service deployment. |
| Session model | Access token 30 min + refresh token 14 days, **rotation with reuse detection**, refresh tokens stored **hashed in Postgres** | Revocable, durable across restarts, no Redis dependency for auth. |
| Tenancy model | **Ownership at the workspace level.** `workspaces.owner_user_id`; every other resource is authorized through its workspace | Neo4j nodes are already keyed `(name, workspace_id)` and Chroma has one collection per workspace — per-user isolation falls out of workspace ownership. **No Neo4j/Chroma changes.** |
| Demo workspace | `arxiv_seed` stays **public**: `owner_user_id = NULL` ⇒ readable by every logged-in user, mutations forbidden | Keeps the seeded demo useful for every account. Reports/conversations get a `user_id` column so history in the shared workspace stays private per user. |
| Organizations | **Deferred.** No `organizations` table yet | Single-user accounts are the product today. The workspace-ownership check is the one choke point to extend later (`owner_user_id` → membership table). |
| Password reset via email | **Out of scope** — no email infra. | Add later with SES (also free-tier). |

---

## 1. Current state (verified 2026-07-04)

- `backend/db/models.py` — models: `Workspace`, `Conversation`, `Report`,
  `Source`, `IngestionJob`. **No User model. No ownership columns.**
- Every route in `backend/api/routes/` accepts any `workspace_id` with no
  identity check.
- Schema migrations run as idempotent `ALTER TABLE ... ADD COLUMN IF NOT
  EXISTS` statements in the `lifespan` of `backend/main.py` — follow that
  pattern; there is no Alembic.
- CORS in `backend/main.py` allows localhost origins but **does not set
  `allow_credentials=True`** — cookies won't flow cross-origin without it.
- Rate limiting: `backend/core/ratelimit.py`, slowapi keyed by remote IP.
- Frontend: no router — `App.tsx` manages tabs via URL params. All HTTP goes
  through the axios client in `frontend/src/api.ts`; streams use `EventSource`.
- MCP server (`backend/mcp/server.py`) runs locally over stdio and calls
  backend modules **directly** (no HTTP) — unaffected by API auth (§9).
- Scripts (`scripts/seed_arxiv.py`, benchmarks, eval harness) also call backend
  modules directly — unaffected.

---

## 2. Data model changes (`backend/db/models.py`)

```python
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=False, unique=True, index=True)  # store lowercased
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, nullable=False, default=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True)   # sha256 of the opaque token
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by = Column(String, nullable=True)  # id of the token that rotated this one
```

New columns on existing tables (nullable, so legacy rows stay valid):

- `workspaces.owner_user_id TEXT NULL` — `NULL` means **public demo workspace**
  (read-only for everyone). Index it.
- `reports.user_id TEXT NULL` — who asked. `NULL` = legacy row.
- `conversations.user_id TEXT NULL` — who owns the thread. `NULL` = legacy row.

Lifespan migration additions in `backend/main.py` (same style as the existing
ones — `create_all` makes the new tables, then):

```sql
ALTER TABLE workspaces    ADD COLUMN IF NOT EXISTS owner_user_id TEXT;
ALTER TABLE reports       ADD COLUMN IF NOT EXISTS user_id TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id TEXT;
CREATE INDEX IF NOT EXISTS ix_workspaces_owner ON workspaces (owner_user_id);
CREATE INDEX IF NOT EXISTS ix_reports_user     ON reports (user_id);
```

The seeded `arxiv_seed` workspace keeps `owner_user_id = NULL` on purpose.
Any *other* pre-existing workspaces are claimable via a one-off script
`scripts/claim_workspaces.py --email <user>` (assigns all NULL-owner
workspaces except `arxiv_seed` to that user). Write it; don't auto-assign.

---

## 3. Auth core (`backend/core/auth.py` — new file)

Responsibilities, all pure logic (unit-testable without FastAPI):

- `hash_password(pw) / verify_password(pw, hash)` — argon2-cffi
  (`PasswordHasher()`; catch `VerifyMismatchError`). Enforce min length 8 at
  the schema level.
- `create_access_token(user_id) -> str` — PyJWT HS256, claims
  `{sub, iat, exp, type: "access"}`, TTL from `ACCESS_TOKEN_TTL_MIN` (default 30).
- `decode_access_token(token) -> user_id | raises` — reject wrong `type`,
  expired, bad signature.
- `new_refresh_token() -> (opaque, sha256_hex)` — `secrets.token_urlsafe(48)`;
  only the hash is stored. TTL from `REFRESH_TOKEN_TTL_DAYS` (default 14).
- Cookie helpers used by the routes:
  - access cookie `kgre_access`: `HttpOnly, SameSite=Lax, Path=/`,
    `Secure` when `COOKIE_SECURE=true` (env; default false for local http).
  - refresh cookie `kgre_refresh`: same flags but `Path=/api/auth` so it is
    only ever sent to the auth endpoints.

`AUTH_SECRET_KEY` is **required** — fail fast at import with a clear error if
unset (same posture as `POSTGRES_URL` in `backend/db/postgres.py`). Add to
`.env.example` with a `python -c "import secrets; print(secrets.token_hex(32))"`
comment.

New deps in `requirements.txt`: `pyjwt>=2.8.0`, `argon2-cffi>=23.1.0`,
`email-validator>=2.0.0` (for pydantic `EmailStr`).

---

## 4. Dependencies (`backend/api/deps.py` — new file)

```python
async def get_current_user(request, db) -> User:
    # 1. Try Authorization: Bearer <jwt>; 2. fall back to kgre_access cookie.
    # decode → load User → 401 if missing/expired/inactive.
    # Set request.state.user_id for the rate limiter (§7).

async def get_owned_workspace(workspace_id, user, db) -> Workspace:
    # 404 if the workspace doesn't exist OR is owned by someone else
    # (404, not 403 — don't leak existence). Demo (owner NULL) is NOT owned.

async def get_readable_workspace(workspace_id, user, db) -> Workspace:
    # owned OR owner_user_id IS NULL (public demo). 404 otherwise.
```

Rules:
- **Read** paths (ask questions, list reports/conversations, graph views,
  suggested questions, list sources) use `get_readable_workspace`.
- **Mutation** paths (create/update/delete workspace, add/delete/retry/reingest
  sources, upload PDF, discover, cleanup) use `get_owned_workspace` — so the
  demo workspace is read-only.
- Routes addressed by non-workspace ids (`/reports/{id}`,
  `/conversations/{id}`) load the row, then authorize via its workspace
  (readable) **and** — when the workspace is the shared demo — require
  `row.user_id == user.id`. Simplest correct filter, applied uniformly:
  visible ⇔ `workspace readable AND (workspace.owner_user_id IS NOT NULL OR row.user_id == user.id OR row.user_id IS NULL)`
  (the `row.user_id IS NULL` arm keeps legacy pre-auth rows visible).

SSE caveat: the two stream endpoints take `workspace_id` as a query param and
authenticate via the cookie like any other route — `EventSource` sends cookies
automatically on same-origin requests. Errors before the stream starts should
return real 401/404 (the frontend's fallback path already handles non-200).

---

## 5. Auth routes (`backend/api/routes/auth.py` — new file, mounted at `/api`)

All rate-limited (see §7). Request/response models in `backend/models/schemas.py`.

| Endpoint | Behavior |
|---|---|
| `POST /auth/register` | `{email, password}`. Lowercase + `EmailStr`-validate email; 409 on duplicate; hash; create user; **auto-login** (issue both tokens, set both cookies). Gate behind `REGISTRATION_ENABLED` env (default `true`; lets a deployed instance close signups). |
| `POST /auth/login` | Verify credentials → set both cookies. Return `{id, email}`. Same 401 message for unknown email vs wrong password. |
| `POST /auth/refresh` | Read `kgre_refresh` cookie → hash → look up. If revoked: **reuse detected** → revoke all of that user's refresh tokens, 401. If valid: rotate (revoke old, `replaced_by` = new id, insert new), issue fresh access + refresh cookies. |
| `POST /auth/logout` | Revoke the presented refresh token; clear both cookies; 204. |
| `GET /auth/me` | `get_current_user` → `{id, email, created_at}`. The frontend's session probe on load. |

No user enumeration: register returns a generic 409 detail; login a generic 401.

---

## 6. Protecting the existing routes

Add `user: User = Depends(get_current_user)` everywhere, and swap raw
`workspace_id` handling for the workspace dependencies. Exact inventory
(current decorators verified):

| File | Routes | Access level |
|---|---|---|
| `questions.py` | `POST /question`, `GET /question/stream` | readable workspace; stamp `report.user_id` and (new threads) `conversation.user_id` |
| `questions.py` | `GET /reports`, `GET /reports/{id}`, `DELETE /reports/{id}` | readable workspace + per-user filter from §4; delete additionally requires `report.user_id == user.id` unless the user owns the workspace |
| `conversations.py` | `GET /conversations`, `GET /conversations/{id}`, `DELETE /conversations/{id}` | same pattern as reports |
| `research.py` | `POST /research/deep`, `GET /research/deep/stream` | readable workspace |
| `graph.py` | `GET /graph`, `/graph/influence`, `/graph/communities`, `/graph/gaps`, `POST /graph/hypothesis` | readable workspace |
| `workspaces.py` | `GET /workspaces` | authenticated; return demo workspaces (owner NULL) **plus** the user's own — filter in SQL, not Python |
| `workspaces.py` | `POST /workspaces` | authenticated; set `owner_user_id = user.id` |
| `workspaces.py` | `PUT/DELETE /workspaces/{id}`, `/discover` | owned |
| `workspaces.py` | `GET .../suggested-questions` | readable |
| `sources.py` | `GET .../sources`, `GET .../sources/{id}/jobs` | readable |
| `sources.py` | all mutations (create, upload, retry, reingest ×2, delete, cleanup) | owned |
| `system.py` | `/system/queue`, `/system/coordinator` | authenticated (any user) |
| `system.py` | `/system/mcp-config` | readable workspace |
| `main.py` | `/health/*`, `/metrics` | **leave unauthenticated** (probes/scraping) |

`GET /reports` and `GET /conversations` currently filter by `workspace_id`
param — add the §4 user filter to the SQL.

### CORS + CSRF (in `backend/main.py`)

- Add `allow_credentials=True` to the CORS middleware (required for cookies;
  the localhost origin regex stays).
- `SameSite=Lax` blocks cross-site POSTs, but `GET /question/stream` **mutates**
  (creates a report) and Lax cookies ride top-level GET navigations. Add a
  small middleware: for any request that is not `GET/HEAD/OPTIONS`, **or** is a
  GET to a path ending in `/stream`, if an `Origin`/`Referer` header is present
  it must match the CORS origin policy (env `FRONTEND_ORIGIN` in prod,
  localhost regex in dev); otherwise 403. Header absent (curl, same-origin
  EventSource in some browsers) → allow — the cookie is still required.

---

## 7. Rate limiting (`backend/core/ratelimit.py`)

- New budgets: `RATE_LIMIT_AUTH` default `10/minute` on register/login/refresh
  (credential-stuffing guard; consistent with the existing per-endpoint style).
- Change `key_func` to prefer the authenticated user:
  `lambda request: getattr(request.state, "user_id", None) or get_remote_address(request)`
  — `get_current_user` sets `request.state.user_id` (§4). Auth endpoints
  themselves are pre-auth, so they naturally key by IP.

---

## 8. Frontend

No router exists — gate at the top of `App.tsx`.

1. **`frontend/src/api.ts`**
   - `withCredentials: true` on the axios client (harmless same-origin; needed
     if `VITE_API_URL` ever points cross-origin).
   - New calls: `register`, `login`, `logout`, `getMe`.
   - Response interceptor: on 401 (and not already an `/api/auth/` URL), call
     `POST /api/auth/refresh` **once** (single-flight: share one in-progress
     refresh promise), retry the original request; if refresh fails, broadcast
     a `kgre:logout` event.
   - Do **not** retry 401 via axios-retry (it only retries network/5xx today —
     keep it that way).
2. **`frontend/src/auth.tsx`** (new) — `AuthProvider` + `useAuth()`. On mount:
   `GET /auth/me` → `{status: "loading" | "anonymous" | user}`. Listens for
   `kgre:logout`.
3. **`frontend/src/components/LoginScreen.tsx`** (new) — combined sign-in /
   create-account card. Use the existing design system: `components/ui`
   primitives (`Button`, `Field`, `Card`, `SectionLabel`) and `lib/palette`.
   Soft, minimal, no emojis. Show API error details (`err.response.data.detail`).
4. **`App.tsx`** — wrap in `AuthProvider`; while `loading` render the existing
   spinner pattern; if `anonymous` render `LoginScreen`; else the current app.
5. **`Rail.tsx`** — account affordance at the bottom: user email + sign-out
   (calls `logout`, then broadcast).
6. **SSE** — the two `EventSource` constructors need
   `{ withCredentials: true }` as the second arg (no-op same-origin, correct
   cross-origin). Before opening a stream the app has already passed the auth
   gate, so a valid access cookie exists; the interceptor keeps it fresh
   because every screen also makes axios calls. Acceptable residual: an access
   token can expire mid-conversation *before* the stream opens — the existing
   error → POST fallback path in `streamQuestion` then hits the interceptor,
   refreshes, and answers, so no extra handling is needed.
7. **`types.ts`** — add `User`.

---

## 9. MCP server & scripts

- `backend/mcp/server.py` runs over stdio on the user's own machine and calls
  the retrieval modules directly — it never crosses the HTTP boundary, so it
  is **out of scope** for cookie auth. Leave it.
- `GET /system/mcp-config` becomes authenticated + readable-workspace (§6), so
  the Connect page only emits configs for workspaces you can see.
- **Later (separate task, not now):** per-user API keys (`api_keys` table,
  `Bearer kgre_<key>` accepted by `get_current_user`) for remote MCP/HTTP
  agents. Design the dependency so this slots in (it already accepts Bearer).
- `scripts/` and the eval harness import backend modules directly —
  unaffected. `scripts/claim_workspaces.py` is the only new script (§2).

---

## 10. AWS free-tier constraints this design satisfies (Phase 7 context)

The Phase 7 table's managed services (Neptune, RDS, OpenSearch, ElastiCache,
Cognito) are **not** free — Neptune has no free tier at all. The free
deployment is: the existing docker-compose stack on **one EC2 instance**
(legacy 750 h/month t-class free tier, or the post-2025 signup-credit plan)
behind Caddy or nginx for TLS. Auth must therefore:

- have **zero AWS dependencies** — it's all FastAPI + Postgres (✓ this design);
- be stateless per request apart from Postgres (any single container restart
  keeps sessions — refresh tokens are in Postgres, access tokens are
  self-validating JWTs) (✓);
- flip to production with env only: `COOKIE_SECURE=true`,
  `FRONTEND_ORIGIN=https://…`, `REGISTRATION_ENABLED` as desired, long random
  `AUTH_SECRET_KEY` (✓).

Note for the eventual deployment (not now): the compose memory limits sum to
~6 GB with all profiles; the free single-node profile (one Neo4j, no
sharding/distributed) needs ~4 GB — pick instance size accordingly. Update the
AGENTS.md Phase 7 table: Cognito row → "self-hosted JWT (built in Phase 6.5);
Cognito optional if ever needed".

---

## 11. New environment variables (add to `.env.example`)

```
AUTH_SECRET_KEY=            # required; python -c "import secrets; print(secrets.token_hex(32))"
ACCESS_TOKEN_TTL_MIN=30
REFRESH_TOKEN_TTL_DAYS=14
COOKIE_SECURE=false         # true behind HTTPS in production
REGISTRATION_ENABLED=true
RATE_LIMIT_AUTH=10/minute
FRONTEND_ORIGIN=            # prod only; dev falls back to the localhost regex
```

---

## 12. Implementation order (each step leaves the app working)

1. Models + lifespan migrations + `.env.example` + requirements (§2, §3 deps).
2. `backend/core/auth.py` + unit tests (hashing, JWT round-trip, expiry,
   wrong-type rejection, refresh-token hashing).
3. Auth routes + `deps.py` + rate limits; test with curl before touching
   existing routes.
4. CORS `allow_credentials` + Origin-check middleware.
5. Protect existing routes per the §6 table; stamp `user_id` on new
   reports/conversations; add the SQL visibility filters.
6. Frontend: api.ts → auth.tsx → LoginScreen → App gate → Rail.
7. `scripts/claim_workspaces.py`.
8. Docs: update AGENTS.md (data models, Phase 7 Cognito row, phase checklist),
   `docs/08-api-reference.md`, `docs/04-configuration.md`, `docs/README.md`.

## 13. Acceptance checklist (verify live, not just by code review)

- [ ] Register → auto-logged-in; second register with same email → 409.
- [ ] Login wrong password → 401 with generic message; 11th attempt in a
      minute → 429.
- [ ] `GET /api/workspaces` with no cookie → 401; with cookie → demo + own only.
- [ ] User A creates a workspace; user B's `GET /api/workspaces/{id}/sources`
      on it → **404** (not 403). Same for reports/conversations/graph routes.
- [ ] Both users ask questions in `arxiv_seed`; each sees only their own
      conversations/reports there. Neither can add or delete a source in it.
- [ ] SSE ask flow works logged in (cookie flows on `EventSource`); after
      clearing cookies the stream errors and the UI lands on the login screen.
- [ ] Wait past access expiry (set `ACCESS_TOKEN_TTL_MIN=1` locally): next API
      call silently refreshes and succeeds; refresh-token reuse (replay an old
      refresh cookie) kills the whole session family.
- [ ] Logout clears cookies; back button doesn't expose data (requests 401).
- [ ] Legacy rows: pre-auth reports in a claimed workspace are still visible
      to the owner (`user_id IS NULL` arm).
- [ ] `pytest` suite passes; `/health/*` and `/metrics` still unauthenticated.
- [ ] Full ingestion loop still works end-to-end as an authenticated user
      (add source → ingest → ask → answer cites data) — per project rule,
      prove source flows live, not by review.
