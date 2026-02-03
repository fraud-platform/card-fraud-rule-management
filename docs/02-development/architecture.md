# Architecture Overview

## System Role

`card-fraud-rule-management` is a **control-plane** service.

It manages rule metadata, governance workflows, and deterministic compilation/publishing.
It does **not** perform runtime transaction evaluation.

## High-Level Responsibilities

- Rule field catalog and metadata
- Rule and rule version lifecycle
- RuleSet identity and RuleSet version lifecycle
- Maker-checker approvals and audit logging
- Deterministic AST compilation
- Ruleset artifact publishing (filesystem or S3/MinIO)
- Field registry versioning and publishing

## Explicit Non-Goals

- Runtime decision execution
- Velocity counter mutation
- Real-time transaction scoring

## Core Architecture Rules

1. UUIDv7 IDs generated in application layer.
2. PostgreSQL schema is `fraud_gov`.
3. Authorization is permission-based (`require_permission`).
4. Maker-checker invariant: maker cannot approve own submission.
5. Compiler output is deterministic and canonical.

Rule evaluation semantics are locked:
- `ALLOWLIST` -> `FIRST_MATCH`
- `BLOCKLIST` -> `FIRST_MATCH`
- `AUTH` -> `FIRST_MATCH`
- `MONITORING` -> `ALL_MATCHING`

## Main Modules

- `app/api/routes/`: HTTP endpoints
- `app/api/schemas/`: request/response models
- `app/repos/`: DB access and business persistence logic
- `app/services/`: service orchestration (publisher/simulation)
- `app/compiler/`: validator, compiler, canonicalizer
- `app/core/`: config, security, middleware, telemetry, DB setup
- `app/db/models.py`: SQLAlchemy models

## Data and Workflow Shape

- Rule lifecycle: draft -> pending approval -> approved/rejected
- RuleSet is split into identity (`rulesets`) and immutable versions (`ruleset_versions`)
- Approval and audit records are immutable history for governance/compliance
- Listing APIs use keyset pagination

## Contracts and Source of Truth

- Machine contract: `docs/openapi.json`
- Human API guide: `../04-api/reference.md`
- Auth model: `../AUTH_MODEL.md`
- ADRs: `../adr/`
