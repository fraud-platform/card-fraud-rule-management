# ADR 0001: Use Doppler for Secrets Management

**Status:** Accepted
**Date:** 2026-01-15
**Context:** Fraud Rule Governance API
**Deciders:** Development Team

## Context

The Fraud Rule Governance API requires secure management of sensitive configuration:

- Database connection strings (with credentials)
- Auth0 client secrets
- API signing keys
- S3/MinIO access keys
- Environment-specific URLs

Previous approaches considered:
- `.env` files (committed to git - insecure)
- Local `.env` files (gitignored - hard to synchronize across team)
- AWS Secrets Manager / Azure Key Vault (complex for local development)

## Decision

**Use Doppler as the primary secrets manager for all environments.**

### Rationale

1. **Unified Secrets Management**
   - Single source of truth for secrets across local, dev, test, and production
   - No secrets committed to git
   - Easy team synchronization

2. **Developer Experience**
   - CLI integration (`doppler run`) works seamlessly with `uv`
   - Local development mirrors production configuration
   - No need to maintain multiple `.env` files

3. **Security**
   - Secrets encrypted at rest
   - Audit trail for secret access
   - Role-based access control
   - Automatic secret rotation support

4. **CI/CD Integration**
   - GitHub Actions integration is straightforward
   - No secrets in CI logs
   - Environment-specific configurations (local, test, prod)

## Implementation

### Doppler Configuration Structure

```
Project: card-fraud-rule-management
├── Environment: local
│   ├── DATABASE_URL_APP
│   ├── AUTH0_CLIENT_ID
│   └── AUTH0_CLIENT_SECRET
├── Environment: test
│   ├── DATABASE_URL_APP (Neon test branch)
│   └── ...
└── Environment: prod
    ├── DATABASE_URL_APP (Neon prod branch)
    └── ...
```

### CLI Integration

```bash
# Local development
uv run doppler-local

# Testing
uv run doppler-local-test  # Local Docker DB
uv run doppler-test        # Neon test branch
uv run doppler-prod        # Neon prod branch
```

### Doppler Commands in pyproject.toml

```toml
[project.scripts]
doppler-local = "cli.doppler_local:main"
doppler-local-test = "cli.doppler_local:test_local"
doppler-test = "cli.doppler_local:test"
doppler-prod = "cli.doppler_local:test_prod"
```

## Consequences

### ALLOWLIST

- **Security:** No secrets in git or local `.env` files
- **Consistency:** All developers use the same configuration structure
- **Onboarding:** New developers run `uv run doppler-local` and are ready
- **CI/CD:** Secrets management is consistent across all environments

### BLOCKLIST

- **Dependency:** Requires Doppler account and CLI installation
- **Network:** Requires internet access for `doppler run`
- **Cost:** Doppler free tier may have limitations for large teams

### Mitigations

- Document Doppler setup process in onboarding guide
- Use scoped service tokens for CI/CD and automation workflows
- Consider Doppler Team plan for production use

## Alternatives Considered

1. **Git-crypted `.env` files**
   - Rejected: Complex setup, merge conflicts on encrypted files

2. **AWS Secrets Manager only**
   - Rejected: No good local development story
   - Accepted as: Future option for production-only secrets

3. **Environment variables in CI/CD only**
   - Rejected: No local development parity
   - Accepted as: CI/CD specific secrets (e.g., deployment tokens)

## References

- [Doppler Documentation](https://docs.doppler.com/)
- [Doppler CLI Guide](https://docs.doppler.com/docs/cli)
- [docs/05-deployment/doppler-secrets-setup.md](../05-deployment/doppler-secrets-setup.md)

## Related Decisions

- [ADR 0002: UUIDv7 for All Identifiers](0002-uuidv7-for-all-identifiers.md)
- [ADR 0003: PostgreSQL with JSONB Hybrid Storage](0003-postgresql-jsonb-hybrid-storage.md)
