# Passivbot API Wrapper Architecture Plan (Stage: Early Design)

## Scope and constraints

- Target steady load: **200–300** bot configurations; hard cap **500**.
- Keep deployment simple first (single service + workers, docker-compose friendly), postpone Kubernetes.
- Persist runtime, historical state, and bot settings in database (PostgreSQL-first), avoid relying on local code-volume files.
- Preserve Passivbot trading behavior as much as possible.
- **Trading mode scope for wrapper v1: multi-asset only** (`n_positions >= 1`, one config can manage many symbols simultaneously).
- Single-asset mode is out of scope for wrapper v1.
- One application user may manage **multiple exchange API key sets** (many accounts per user).
- First operator interface for wrapper v1 is a **Telegram bot** (thin client over wrapper API).

## Bootstrapping and database initialization

- Application starts from explicit settings: `POSTGRES_DSN` + `POSTGRES_SCHEMA`.
- For shared PostgreSQL with multiple projects/instances, each wrapper deployment must use its own schema.
- Recommended naming: `pbwrap_<instance_id>` where `instance_id` is numeric (`1`, `2`, `3`, ...).
- On startup, service executes bootstrap routine:
  1. ensure target schema exists (`CREATE SCHEMA IF NOT EXISTS <schema>`)
  2. ensure migrations table exists in that schema
  3. run pending migrations for all required tables/indexes
- If bootstrap fails, service must fail fast and not start workers.
- No local JSON/file initialization path in wrapper mode (all runtime settings loaded from DB).

## Project structure (where to implement)

Start in a **separate folder inside this repo** to isolate wrapper code from passivbot core while reusing modules:

- `wrapper/`
  - `api/` (FastAPI endpoints)
  - `worker/` (runtime executor, scheduling loops)
  - `db/` (models, migrations, repositories)
  - `integrations/telegram/` (Telegram transport layer)
  - `adapters/passivbot/` (bridge to existing passivbot runtime)
  - `schemas/` (Pydantic request/response and config validation)

This keeps boundary explicit: passivbot remains source trading engine, wrapper owns orchestration/API/product layer.

## What to reuse vs wrap vs rewrite

### Reuse as-is (high confidence)

1. **Rust order calculation path** via `passivbot_rust` (source of truth for behavior).
2. **Core orchestration behavior in `Passivbot`**:
   - live execution loop orchestration
   - order reconciliation (`calc_orders_to_cancel_and_create`)
   - execution gates and throttles (recent updates/cancellations, state-change skip)
3. **Exchange adapters (`CCXTBot` + exchange subclasses)** for mature exchange-specific behavior.
4. **Normalization contracts** (signed qty, `position_side`, custom-id mapping, etc.).

### Wrap with adapter layer (recommended)

1. **Configuration source**
   - Replace file-based user/config loading (`api-keys.json`, runtime config files).
   - Inject config and credentials from DB/secrets provider into Passivbot-compatible dicts.

2. **Market data persistence**
   - Keep CandlestickManager fetch/transform logic, but add storage adapter so canonical candles are persisted in PostgreSQL.
   - Optional short-term in-memory cache remains for speed; DB remains source of truth.

3. **Fills/PnL persistence**
   - Keep fetch/canonicalization behavior from `FillEventsManager`.
   - Replace day-json cache with DB tables and metadata rows.

4. **Rate-limit coordination**
   - Replace temp-file coordinator with PostgreSQL-backed coordinator (Redis optional later).
   - Encode default policy `600 requests / 5 min` and per-exchange overrides.

5. **Lifecycle and scheduling**
   - Add control plane around Passivbot instances (start/stop/pause/restart, lease ownership, heartbeat).

### Rewrite outside passivbot (new service components)

1. **API server** (FastAPI)
   - CRUD configs and instances
   - lifecycle commands
   - status and metrics endpoints

2. **Control-plane scheduler**
   - Assign instances to workers
   - recover orphaned sessions
   - stagger ticks/jitter to avoid API bursts

3. **Worker runtime wrapper**
   - Host many logical bot instances per process
   - call Passivbot internals in controlled cycles
   - emit metrics/events to DB

4. **Observability pipeline**
   - DB-first run metrics and event stream
   - optional Prometheus export later

## How configuration is passed into bot runtime

Short answer: **not only API calls to passivbot**, but API calls to wrapper + internal runtime snapshots.

1. Operator (or UI) writes config via wrapper API (`POST /configs`, `POST /instances/{id}/start`).
2. Wrapper validates config against Passivbot-compatible schema.
3. Wrapper stores immutable config version in DB (`bot_configs.version`).
4. Worker receives run command and loads config version + account credentials from DB.
5. Worker materializes a **runtime snapshot dict** compatible with Passivbot expected structure.
6. Worker creates/updates bot instance in memory and runs execution cycle.

This means:

- external interface is API-centric,
- internal pass-through to passivbot remains in-process Python calls,
- config provenance is fully auditable in DB.

## Multi-asset mode only (wrapper v1 policy)

- Accept only configs where symbol universe is multi-asset capable.
- Validation rule: config must not be restricted to single-symbol-only mode.
- Runtime guard: if resolved active symbol set has size 0 -> instance `error`; if size 1 it is still allowed as a temporary state, but config semantics remain multi-asset.
- For scheduling and capacity planning, assume each instance may trade many symbols concurrently.

## Config format strategy (stay close to Passivbot)

Use current Passivbot config model as canonical source and map DB schema around it.

### Storage principle

- Keep full config in JSONB (`bot_configs.config_json`) in **Passivbot-native shape**.
- Avoid flattening all strategy params into SQL columns initially.
- Extract selected indexed fields for operations/filtering only (exchange, user, enabled flags, mode).

### Recommended sections

- Preserve hierarchy equivalent to:
  - `config.live` (runtime behavior)
  - `config.backtest` (keep optional for compatibility, mostly unused in wrapper runtime)
  - `config.optimize` (stored but not used by wrapper runtime)
- Preserve `bot.long` / `bot.short` parameter structures and coin overrides as close as possible.

### Why this approach

- maximum compatibility with existing passivbot logic,
- easier import/export from existing JSON/HJSON configs,
- lower migration risk when upstream passivbot adds fields.

## Proposed execution pipeline (aligned to your 3-thread idea)

Use **3 logical stages** (may be async tasks, not strict OS threads):

1. **Data stage (collector)**
   - refresh positions/balance/open orders/ohlcv/fills
   - write snapshots and deltas to DB
   - produce `calc-ready` job

2. **Calculation stage (planner)**
   - build snapshot input
   - call orchestrator path (`calc_ideal_orders_orchestrator`)
   - persist calculation result and latency metrics
   - produce `execution-ready` job

3. **Execution stage (reconciler/executor)**
   - compare ideal vs live
   - apply create/cancel only when needed (same behavior as passivbot)
   - persist execution attempts, exchange responses, errors

This keeps behavior close to current passivbot while allowing per-stage scaling later.

## Minimal data model to start (PostgreSQL)

### 1) Configuration & lifecycle

- `users`
  - wrapper user entity (operator/tenant)
  - `id`, `external_id` (e.g., telegram user id), `role`, `status`, `created_at`
- `accounts`
  - trading account/API-key entity (many per user)
  - `id`, `user_id`, `exchange`, `account_label`, `status`, `created_at`
- `api_key_sets`
  - versioned credentials per account (rotation-friendly)
  - `id`, `account_id`, `key_ref`, `secret_ref`, `passphrase_ref`, `is_active`, `created_at`, `disabled_at`
- `credentials`
  - optional: if secret manager is not used immediately, encrypted payload storage
  - `api_key_set_id`, `encrypted_payload`, `kek_version`, `updated_at`
- `bot_configs`
  - `id`, `version`, `config_json`, `created_at`, `is_active`
- `bot_settings`
  - global runtime settings for wrapper service (rate limits, scheduling, timeouts, feature flags)
  - `key`, `value_json`, `updated_at`, `updated_by`
- `bot_instances`
  - `id`, `account_id`, `config_id`, `status` (`running|paused|stopped|error`), `worker_id`, `runtime_version`, `updated_at`

### 2) Runtime state snapshots

- `instance_state_snapshots`
  - `instance_id`, `ts`, `balance`, `equity`, `positions_json`, `open_orders_json`
- `market_data_1m`
  - `exchange`, `symbol`, `ts`, `o`, `h`, `l`, `c`, `bv`
  - unique `(exchange, symbol, ts)`
- `fills`
  - canonical fill event fields (`exchange_trade_id`, `symbol`, `side`, signed `qty`, `price`, `pnl`, `timestamp`, `raw_json`)

### 3) Calculation and execution metrics (required)

- `calc_runs`
  - `id`, `instance_id`, `cycle_id`, `started_at`, `finished_at`, `status`, `error`
  - `symbols_count`, `orders_planned_count`, `duration_ms`

- `calc_order_metrics`
  - `calc_run_id`, `symbol`, `position_side`, `order_type`, `qty`, `price`
  - `calc_started_at`, `calc_finished_at`, `calc_duration_ms`

- `execution_runs`
  - `id`, `instance_id`, `cycle_id`, `started_at`, `finished_at`, `status`
  - `orders_to_create`, `orders_to_cancel`, `created_ok`, `cancelled_ok`, `duration_ms`

- `execution_attempts`
  - `execution_run_id`, `action` (`create|cancel`), `symbol`, `order_ref`, `request_payload`, `response_payload`, `status`, `error`, `latency_ms`

> `cycle_id` links data->calc->execution in one loop for end-to-end latency analysis.

## PostgreSQL-only mode vs Redis (decision)

### Can we run everything in PostgreSQL?

Yes. For the first version (200–300 instances), we can run **PostgreSQL-only** and keep architecture simpler.

Use Postgres for:

- job queue tables (`queue_collect`, `queue_calculate`, `queue_execute`) with `SELECT ... FOR UPDATE SKIP LOCKED`
- leases/heartbeats in DB tables
- rate-limit counters in short-window tables
- event stream and metrics (already DB-first)

### Why Redis might still be useful later

Redis becomes valuable when we need lower-latency coordination and cheaper high-frequency ephemeral state:

- faster queue ops under bursty load
- lightweight distributed locks with TTL semantics
- cheap sliding-window counters/token buckets for rate limiting
- pub/sub for live status streaming

### Practical recommendation now

1. Start with **PostgreSQL-only** (fewer dependencies, simpler operations).
2. Keep queue/rate-limit interfaces abstract (`QueueBackend`, `RateLimitBackend`).
3. Add Redis only if Postgres queue contention or latency becomes a measurable bottleneck.

## Rate limit strategy (initial)

- Global default: `600 req / 5 min` window.
- In PostgreSQL-only mode: maintain rolling counter per `(exchange, account)` via DB windowed counters.
- In Redis mode (optional later): use sorted sets or token buckets.
- Planner marks each job with estimated API cost; executor waits if budget exhausted.
- Add jitter around boundary to avoid synchronized bursts.

## Service layout for MVP (without K8s complexity)

- `pb-api` (FastAPI)
- `pb-worker` (N replicas, each handles many instances)
- `postgres`
- `redis` (optional, phase 2+ if needed)

Run via docker-compose first. Add horizontal workers before introducing Kubernetes.

## Telegram as first control interface

- Telegram bot is a client of wrapper API, not a place where trading logic lives.
- Telegram commands map to API operations:
  - `/accounts` -> list user accounts/api key sets
  - `/instances` -> list bot instances
  - `/start <instance>` `/stop <instance>` `/status <instance>`
  - `/set_config <instance> <version>`
- Telegram bot should authenticate user identity and map to `users.external_id`.
- All actions remain auditable in DB (`actor_user_id`, `source=telegram`).

## Where to start implementation (recommended order)

1. **Data models + migrations first**
   - users/accounts/api_key_sets/configs/instances/runs
   - schema bootstrap via `POSTGRES_DSN` + `POSTGRES_SCHEMA`
2. **Config compatibility layer**
   - passivbot-native JSONB validation and round-trip import/export
3. **Minimal worker + one cycle execution**
   - load instance from DB -> run one data/calc/execute cycle -> persist metrics
4. **API endpoints for lifecycle**
   - create account/config/instance, start/stop/status
5. **Telegram thin shell**
   - command routing to API with auth/audit

This order minimizes integration risk and gives verifiable checkpoints early.

## Phased implementation + readiness criteria (what to verify before moving on)

### Phase 0 — schema + config compatibility

Deliverables:

- DB schema/migrations with `POSTGRES_SCHEMA` bootstrap
- user/account/api_key_set model with one-to-many user->accounts
- config validator compatible with passivbot-native config shape
- import path for existing JSON/HJSON configs

Ready when:

- app boots on empty DB and auto-creates schema/tables
- can create user + multiple accounts(api key sets) + config/instance via API
- config round-trip (import/export) is lossless

### Phase 1 — one-instance runtime parity

Deliverables:

- worker can run one multi-asset instance from DB config
- data/calc/execute cycle persisted to DB
- basic rate-limit enforcement (`600/5m`)

Ready when:

- one instance survives restart and resumes from DB state
- orders produced/executed are consistent with baseline passivbot behavior for same inputs
- `calc_runs` + `execution_runs` populated for every cycle

### Phase 2 — controlled concurrency (50–100 instances)

Deliverables:

- queue/lease mechanics for multiple workers
- health checks, stuck lease recovery, retries
- basic operational dashboards over DB metrics

Ready when:

- no duplicate active lease per instance
- failed worker handoff < target SLA (define e.g. 30–60s)
- sustained run shows stable cycle latency and no uncontrolled rate-limit breaches

### Phase 3 — scale target (200–300, peak 500)

Deliverables:

- tuned scheduling and batching
- partitioning/indexing for hot tables
- soak tests and failure drills

Ready when:

- 24h soak test at target load passes
- DB write/read latencies remain within SLO
- exchange error spikes do not cascade into system-wide stalls

## Migration approach from existing passivbot file caches

1. Keep current behavior operational.
2. Add DB persistence alongside existing file writes (dual-write phase).
3. Validate parity (counts, timestamps, pnl totals).
4. Switch reads to DB-backed adapters.
5. Disable file persistence in wrapper mode.

## What is often missed at planning stage (important checklist)

1. **Config migration/versioning**
   - how old config versions are upgraded when passivbot introduces new fields.
2. **Secrets model**
   - encryption at rest, rotation process, audit trail, RBAC boundaries.
3. **Idempotency**
   - start/stop/restart and order execution retries must be idempotent.
4. **Clock/time policy**
   - NTP drift handling and canonical timestamp source for cycle metrics.
5. **Reconciliation policy**
   - explicit rules for resolving DB state vs exchange state conflicts.
6. **Operational runbooks**
   - procedures for stuck instance, exchange outage, API key revoke, schema migration rollback.
7. **Cost controls**
   - expected DB growth for candles/fills/metrics and retention strategy from day 1.
8. **Acceptance test pack**
   - deterministic replay scenarios to compare wrapper vs original passivbot decisions.

## Open decisions to close before schema freeze

1. One process with many asyncio tasks vs multiple worker processes per host?
2. DB partitioning strategy from day 1 (`fills`, `market_data_1m`, metrics tables)?
3. Secret storage: encrypted in Postgres vs external secret manager?
4. How much of CandlestickManager should remain file-compatible in transition mode?
