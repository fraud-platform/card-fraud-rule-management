# ADR 0006: Control Plane vs Runtime Separation

**Status:** Accepted
**Date:** 2026-01-15
**Context:** Fraud Rule Governance API
**Deciders:** Development Team

## Context

Fraud detection requires two distinct capabilities:

1. **Governance:** Define, approve, version, and audit rules
2. **Execution:** Evaluate transactions and update counters

Attempting to combine these in one system creates:

- **Performance Conflicts:** Governance needs consistency; execution needs speed
- **Scaling Conflicts:** Governance handles low-volume admin; execution handles high-volume transactions
- **Complexity:** Mixing concerns makes both systems harder to maintain

Architecture approaches considered:
- Monolithic system (rejected: concerns mixed)
- Event-driven microservices (selected: clean separation)

## Decision

**Separate control plane (this system) from runtime (Quarkus) with artifact-based deployment.**

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   CONTROL PLANE (FastAPI)                    │
│                                                               │
│  - Rule definition and metadata management                   │
│  - Maker-checker governance                                 │
│  - RuleSet versioning and approval                           │
│  - Deterministic AST compilation                            │
│  - Artifact publishing to S3                                │
│                                                               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          │ Artifact (JSON)
                          │ Published to S3
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     RUNTIME (Quarkus)                        │
│                                                               │
│  - Fetch artifacts from S3                                  │
│  - Cache AST in memory                                       │
│  - Evaluate transactions against rules                      │
│  - Update Redis velocity counters                           │
│  - Apply actions (ALLOW, BLOCK, FLAG)                       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Responsibility Separation

| Concern | Control Plane | Runtime |
|---------|---------------|---------|
| **Rule Definition** | ✅ Create, edit, version rules | ❌ Not involved |
| **Governance** | ✅ Maker-checker, approval workflow | ❌ Not involved |
| **Compilation** | ✅ Generate deterministic AST | ❌ Not involved |
| **Artifact Storage** | ✅ Publish to S3 | ✅ Read from S3 |
| **Evaluation** | ❌ Not involved | ✅ Execute per transaction |
| **Velocity State** | ✅ Define velocity fields | ✅ Update Redis counters |
| **Audit Trail** | ✅ All state changes logged | ✅ Evaluation results |

### Integration Contract

**Control Plane Publishes:**

```json
{
  "rulesetId": "01918052-461f-74e3-8000-000000000001",
  "version": 7,
  "ruleType": "AUTH",
  "evaluation": {"mode": "FIRST_MATCH"},
  "velocityFailurePolicy": "SKIP",
  "rules": [
    {
      "ruleId": "01918052-1234-5678-9000-000000000001",
      "priority": 100,
      "when": {
        "and": [
          {"field": "amount", "op": "GT", "value": 3000},
          {"field": "velocity_txn_count_5m_by_card", "op": "GT", "value": 5}
        ]
      },
      "action": "BLOCK",
      "scope": {"country": ["IN"]}
    }
  ]
}
```

**Runtime Consumes:**

1. Polls S3 for new artifacts (or subscribes to notifications)
2. Validates AST schema version
3. Caches rules in memory
4. Evaluates each transaction against rules
5. Returns decision + matched rule IDs

## Rationale

1. **Technology Fit**
   - FastAPI excels at admin interfaces and governance workflows
   - Quarkus excels at high-performance, low-latency evaluation

2. **Independent Scaling**
   - Control plane: Scale based on admin traffic (low volume)
   - Runtime: Scale based on transaction volume (high volume)

3. **Deployment Independence**
   - Control plane updates don't affect transaction processing
   - Runtime can cache artifacts and run even if control plane is down

4. **Team Autonomy**
   - Governance team focuses on control plane
   - Platform team focuses on runtime optimization

## Implementation

### Artifact Publishing (Control Plane)

```python
class RuleSetPublisher:
    """Publish approved rulesets to S3 for runtime consumption."""

    def publish(self, ruleset_version: RuleSetVersion) -> ArtifactManifest:
        """Compile, publish, and track artifact."""

        # 1. Compile to AST
        ast = self.compile_ruleset(ruleset_version)

        # 2. Serialize deterministically
        artifact_json = canonicalize_json(ast)
        checksum = sha256(artifact_json.encode()).hexdigest()

        # 3. Determine artifact path
        environment = ruleset_version.ruleset.environment
        ruleset_key = self.map_rule_type(ruleset_version.ruleset.rule_type)
        version = ruleset_version.version
        path = f"{environment}/{ruleset_key}/v{version}.json"

        # 4. Upload to S3
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=path,
            Body=artifact_json,
            Metadata={"checksum": checksum}
        )

        # 5. Track in database
        manifest = RuleSetManifest(
            ruleset_manifest_id=uuid7(),
            environment=environment,
            ruleset_key=ruleset_key,
            ruleset_version=version,
            artifact_uri=f"s3://{self.bucket_name}/{path}",
            checksum=checksum,
            created_by=get_user_id(),
        )
        db.add(manifest)

        return manifest
```

### Rule Type Mapping

| Control Plane RuleType | Runtime Ruleset Key | Description |
|------------------------|---------------------|-------------|
| `AUTH` | `CARD_AUTH` | Authorization decisioning |
| `MONITORING` | `CARD_MONITORING` | Post-authorization analytics |

**Note:** `ALLOWLIST` and `BLOCKLIST` rules are compiled within the `AUTH` context, not published separately.

## Consequences

### ALLOWLIST

- **Clear Separation:** Each system has focused responsibilities
- **Independent Scaling:** Optimal scaling for each workload
- **Failure Isolation:** Control plane issues don't affect transactions
- **Technology Flexibility:** Best tool for each job

### BLOCKLIST

- **Deployment Latency:** Runtime may use stale rules during polling interval
- **Coordination:** Schema changes require coordination between teams
- **Debugging:** Need to correlate logs across systems

### Mitigations

- **Polling Frequency:** Runtime polls every 30 seconds (configurable)
- **Schema Versioning:** AST includes `astVersion` for backward compatibility
- **Correlation IDs:** Shared request IDs for distributed tracing
- **Health Checks:** Runtime reports loaded artifact version

## Alternatives Considered

1. **Monolithic System**
   - Rejected: Mixed concerns, hard to scale independently
   - Governance needs would slow down transaction processing

2. **Database Polling**
   - Rejected: Runtime would query control plane database directly
   - Creates tight coupling and performance issues

3. **Event Bus Integration**
   - Deferred: Could use SNS/SQS for artifact change notifications
   - Current approach: S3 polling is simpler and sufficient

## References

- [Ruleset Publisher Documentation](../03-api/ruleset-publisher.md)
- [Architecture Documentation](../02-development/architecture.md)
- [Domain Model Documentation](../07-reference/domain-model.md)

## Related Decisions

- [ADR 0005: Deterministic Rule Compiler](0005-deterministic-rule-compiler.md)
- [ADR 0007: Velocity State at Runtime Only](0007-velocity-state-runtime-only.md)
