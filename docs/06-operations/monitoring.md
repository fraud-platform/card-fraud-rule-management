# Monitoring and Alerting Guide

This guide covers monitoring, metrics, logging, and alerting for the Fraud Rule Governance API.

> **Note**: This is a greenfield project with no backward compatibility concerns. All code choices prioritize simplicity and correctness over supporting legacy implementations.

## Overview

The application includes built-in observability features:

- **Structured logging**: JSON logs with correlation IDs
- **Prometheus metrics**: HTTP, database, and compiler metrics
- **Health endpoints**: Liveness and readiness checks
- **Request tracing**: Correlation ID propagation
- **OpenTelemetry distributed tracing**: End-to-end trace visualization

## Observability Features

### Structured Logging

All logs are formatted as JSON with standard fields:

```json
{
  "timestamp": "2026-01-11T10:30:45.123Z",
  "level": "INFO",
  "logger": "app.request",
  "message": "GET /api/v1/rules",
  "request_id": "req-abc123",
  "user_id": "auth0|123456",
  "region": "us-east-1",
  "method": "GET",
  "route": "/api/v1/rules",
  "status_code": 200,
  "latency_ms": 45.67
}
```

**Benefits:**
- Machine-readable for log aggregation
- Correlation IDs for request tracing
- Structured queries in log management tools

### OpenTelemetry Distributed Tracing

The API automatically generates distributed traces using OpenTelemetry, providing end-to-end visibility into request flows across services.

#### Configuration

OpenTelemetry is configured via environment variables:

```bash
# Enable/disable tracing (default: true)
OTEL_ENABLED=true

# Service name for traces (default: fraud-governance-api)
OTEL_SERVICE_NAME=fraud-governance-api

# OTLP collector endpoint (default: http://localhost:4317)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

# Optional headers for OTLP exporter (e.g., for authentication)
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer token

# Sampling strategy (default: parent_trace_always)
# Options: parent_trace_always, always_on, always_off, traceidratio
OTEL_TRACES_SAMPLER=parent_trace_always

# Sampling rate for traceidratio (default: 1.0)
OTEL_TRACES_SAMPLER_ARG=1.0
```

#### Instrumentation

The following components are automatically instrumented:

**FastAPI (HTTP Layer)**
- All incoming HTTP requests
- Captures route patterns, HTTP methods, status codes
- Adds span attributes: `http.method`, `http.route`, `http.status_code`

**SQLAlchemy (Database Layer)**
- All database queries
- Captures query text, execution time
- Adds span attributes: `db.system`, `db.name`, `db.statement`

**HTTPX (Outbound HTTP)**
- All outgoing HTTP requests (e.g., to Auth0)
- Captures URL, method, status code
- Adds span attributes: `http.method`, `http.url`

#### Trace Context in Logs

Structured logs automatically include trace context from OpenTelemetry:

```json
{
  "timestamp": "2026-01-14T10:30:45.123Z",
  "level": "INFO",
  "logger": "app.request",
  "message": "GET /api/v1/rules",
  "request_id": "req-abc123",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "user_id": "auth0|123456",
  "region": "us-east-1",
  "method": "GET",
  "route": "/api/v1/rules",
  "status_code": 200,
  "latency_ms": 45.67
}
```

**Benefits:**
- Correlate logs with traces in your observability platform
- Search all logs for a specific trace ID to see the full request journey
- Understand performance bottlenecks across service boundaries

#### Setting Up Jaeger (Local Development)

For local development, you can run Jaeger to visualize traces:

```bash
# Using Docker
docker run -d \
  --name jaeger \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 16686:16686 \
  jaegertracing/all-in-one:latest

# Access Jaeger UI
open http://localhost:16686
```

**Ports:**
- `4317`: OTLP gRPC receiver (used by default)
- `4318`: OTLP HTTP receiver
- `16686`: Jaeger web UI

#### Setting Up OTLP Collector (Production)

For production, deploy an OpenTelemetry Collector:

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  batch:

exporters:
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger]
```

```bash
docker run -d \
  --name otel-collector \
  -v $(pwd)/otel-collector-config.yaml:/etc/otelcol-contrib/config.yaml \
  -p 4317:4317 \
  otel/opentelemetry-collector-contrib:latest
```

#### Sampling Strategies

**Parent-based sampling (default)**
```bash
OTEL_TRACES_SAMPLER=parent_trace_always
OTEL_TRACES_SAMPLER_ARG=1.0
```
- Respects parent trace context
- Samples 100% of root spans
- Best for: Development, testing

**Always-on**
```bash
OTEL_TRACES_SAMPLER=always_on
```
- Samples 100% of traces
- Best for: Low-traffic environments

**Always-off**
```bash
OTEL_TRACES_SAMPLER=always_off
```
- No tracing
- Best for: Performance-critical scenarios

**Trace ID ratio-based**
```bash
OTEL_TRACES_SAMPLER=traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
```
- Samples percentage of traces
- Best for: High-traffic production environments
- Example: `0.1` = 10% of traces

#### Testing Telemetry Setup

The project includes a standalone manual check to verify OpenTelemetry configuration:

```powershell
doppler run --project=card-fraud-rule-management --config=local -- uv run python scripts/manual_checks/check_telemetry_setup.py
```

This test verifies:
- Telemetry module can be imported
- Trace context functions work correctly
- Configuration parsing works
- Resource creation succeeds
- Observability integration is functional

#### Viewing Traces

Once configured, traces will appear in your backend:

**Jaeger UI:**
1. Navigate to http://localhost:16686
2. Select service: `fraud-governance-api`
3. Click "Find Traces"
4. Click on a trace to see detailed span information

**Common Span Attributes:**
- `service.name`: fraud-governance-api
- `service.version`: 0.1.0
- `deployment.environment`: local/test/production
- `app.region`: us-east-1
- `http.method`: GET/POST/PUT/PATCH/DELETE
- `http.route`: /api/v1/rules
- `http.status_code`: 200/400/401/404/500
- `db.system`: postgresql
- `db.name`: fraud_gov

#### Troubleshooting OpenTelemetry

**No traces appearing:**
```bash
# Verify environment variables
env | grep OTEL

# Check if tracing is enabled
OTEL_ENABLED=true

# Verify collector endpoint
curl -v http://localhost:4317
```

**Missing trace context in logs:**
- Verify `observability_structured_logs=true`
- Check that `OTEL_ENABLED=true`
- Ensure traces are being sampled (check `OTEL_TRACES_SAMPLER`)

**High memory usage:**
- Reduce sampling rate: `OTEL_TRACES_SAMPLER_ARG=0.1`
- Use `traceidratio` sampler for high-traffic scenarios
- Increase batch processor size in collector config

### Prometheus Metrics

Metrics are exposed at `/metrics` endpoint in Prometheus format:

```prometheus
# HTTP requests
http_requests_total{method="GET",route="/api/v1/rules",status_code="200",region="us-east-1"} 1234.0

# Request latency
http_request_duration_seconds_bucket{method="GET",route="/api/v1/rules",region="us-east-1",le="0.1"} 1200.0

# In-flight requests
http_requests_in_progress{method="GET",route="/api/v1/rules",region="us-east-1"} 2.0

# Errors
http_errors_total{error_type="ValidationError",method="POST",route="/api/v1/rules",region="us-east-1"} 5.0

# Database pool
db_pool_size{region="us-east-1"} 20.0
db_pool_checked_out{region="us-east-1"} 8.0

# Compiler performance
compiler_duration_seconds_sum{region="us-east-1"} 123.456
compiler_compilations_total{status="success",region="us-east-1"} 45.0
```

### Health Endpoints

- **`/api/v1/health`**: Liveness check (application is running)
- **`/api/v1/readyz`**: Readiness check (application + dependencies healthy)

## Key Metrics to Monitor

### Request Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `http_requests_total` | Counter | Total HTTP requests by method, route, status |
| `http_request_duration_seconds` | Histogram | Request latency (p50, p95, p99) |
| `http_requests_in_progress` | Gauge | Currently executing requests |
| `http_errors_total` | Counter | Total errors by type |

**Alert Thresholds:**
- Error rate > 5% for 5 minutes
- p95 latency > 1 second for 5 minutes
- p99 latency > 5 seconds for 5 minutes
- Request rate < 1/min (may indicate outage)

### Database Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `db_pool_size` | Gauge | Total connection pool size |
| `db_pool_checked_out` | Gauge | Connections currently in use |
| `db_query_duration_seconds` | Histogram | Database query latency |
| `db_queries_total` | Counter | Total queries by operation, status |

**Alert Thresholds:**
- Pool checked out > 90% of pool size for 5 minutes
- Query p95 latency > 500ms for 5 minutes
- Query error rate > 1% for 5 minutes

### Compiler Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `compiler_duration_seconds` | Histogram | Ruleset compilation time |
| `compiler_rules_count` | Histogram | Number of rules in ruleset |
| `compiler_ast_bytes` | Histogram | Compiled AST size in bytes |
| `compiler_compilations_total` | Counter | Total compilations by status |

**Alert Thresholds:**
- Compilation failure rate > 10% for 15 minutes
- Compilation p95 latency > 10 seconds for 15 minutes
- AST size > 10 MB (may indicate issue)

### Security Metrics

| Metric | Type | Description |
|--------|------|-------------|
| Security event logs | - | Auth failures, authz failures |
| Rate limit violations | - | From rate_limit middleware |

**Alert Thresholds:**
- Auth failure rate > 10% for 5 minutes (possible attack)
- More than 100 rate limit violations per minute

## Logging Configuration

### Log Levels

```python
# In app/core/config.py
APP_LOG_LEVEL: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

**Recommendations:**
- Development: `DEBUG`
- Staging: `INFO`
- Production: `INFO` (or `WARNING` to reduce volume)

### Log Format

Logs are formatted as JSON when `observability_structured_logs=true`:

```python
# Enable structured logging
from app.core.observability import configure_structured_logging
configure_structured_logging("INFO")
```

### Log Fields

Standard fields included in all logs:
- `timestamp`: ISO 8601 format
- `level`: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `logger`: Logger name (typically module name)
- `message`: Log message
- `request_id`: Correlation ID (if available)
- `user_id`: Authenticated user (if available)
- `region`: Geographic region

### Adding Context to Logs

```python
import logging

logger = logging.getLogger(__name__)

logger.info(
    "Ruleset compiled",
    extra={
        "ruleset_id": str(ruleset_id),
        "rule_count": len(rules),
        "compilation_time_ms": duration,
    }
)
```

## Log Analysis

### Querying Logs

**Using Elasticsearch/OpenSearch:**
```json
{
  "query": {
    "bool": {
      "must": [
        {"match": {"level": "ERROR"}},
        {"range": {"timestamp": {"gte": "now-1h"}}}
      ]
    }
  }
}
```

**Using CloudWatch Logs Insights:**
```sql
fields @timestamp, level, message, user_id
| filter level = "ERROR"
| sort @timestamp desc
| limit 100
```

**Using Loki/Grafana:**
```
{level="ERROR"} |= "database"
```

### Request Tracing

Find all logs for a specific request:

```bash
# Get request ID from response header
curl -I http://localhost:8000/api/v1/rules
# X-Request-ID: req-abc123

# Search logs for this request
docker logs container_id | grep "req-abc123"

# Or in log management tool
# request_id="req-abc123"
```

### Common Log Queries

**All errors in last hour:**
```
level:ERROR AND timestamp:[now-1h TO now]
```

**Database errors:**
```
level:ERROR AND message:(database OR postgres OR psycopg)
```

**Authentication failures:**
```
event_type:"AUTH_FAILURE"
```

**Slow requests (>1 second):**
```
latency_ms:>1000
```

## Alerting

### Alerting Strategy

**Severity Levels:**

| Severity | Response Time | Examples |
|----------|--------------|----------|
| **Critical** | 15 minutes | Application down, database unavailable |
| **High** | 1 hour | High error rate, performance degradation |
| **Medium** | 4 hours | Elevated error rate, minor issues |
| **Low** | 1 day | Informational, trends |

### Prometheus Alerting Rules

Create `alerts.yml` for Prometheus Alertmanager:

```yaml
groups:
  - name: fraud_governance_api
    interval: 30s
    rules:
      # Application is down
      - alert: ApplicationDown
        expr: up{job="fraud-governance-api"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Application is down"
          description: "{{ $labels.instance }} has been down for more than 2 minutes"

      # High error rate
      - alert: HighErrorRate
        expr: |
          (
            sum(rate(http_errors_total{job="fraud-governance-api"}[5m]))
            /
            sum(rate(http_requests_total{job="fraud-governance-api"}[5m]))
          ) > 0.05
        for: 5m
        labels:
          severity: high
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value | humanizePercentage }} for the last 5 minutes"

      # High latency
      - alert: HighLatency
        expr: |
          histogram_quantile(0.95,
            sum(rate(http_request_duration_seconds_bucket{job="fraud-governance-api"}[5m])) by (le)
          ) > 1
        for: 5m
        labels:
          severity: high
        annotations:
          summary: "High request latency"
          description: "p95 latency is {{ $value }}s for the last 5 minutes"

      # Database pool exhausted
      - alert: DatabasePoolExhausted
        expr: |
          db_pool_checked_out{job="fraud-governance-api"}
          /
          db_pool_size{job="fraud-governance-api"} > 0.9
        for: 5m
        labels:
          severity: high
        annotations:
          summary: "Database pool nearly exhausted"
          description: "{{ $value | humanizePercentage }} of pool is checked out"

      # Compiler failures
      - alert: CompilerFailures
        expr: |
          sum(rate(compiler_compilations_total{status="error",job="fraud-governance-api"}[15m]))
          /
          sum(rate(compiler_compilations_total{job="fraud-governance-api"}[15m])) > 0.1
        for: 15m
        labels:
          severity: medium
        annotations:
          summary: "High compiler failure rate"
          description: "Compiler failure rate is {{ $value | humanizePercentage }}"

      # Auth failures (possible attack)
      - alert: HighAuthFailureRate
        expr: |
          sum(rate(http_errors_total{error_type="UnauthorizedError",job="fraud-governance-api"}[5m])) > 10
        for: 5m
        labels:
          severity: medium
        annotations:
          summary: "High authentication failure rate"
          description: "{{ $value }} auth failures per second for the last 5 minutes"
```

### Alert Notifications

Configure Alertmanager to send notifications:

```yaml
# alertmanager.yml
receivers:
  - name: 'slack-critical'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#alerts-critical'
        title: '🚨 {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'

  - name: 'slack-high'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'
        channel: '#alerts-high'

  - name: 'email-oncall'
    email_configs:
      - to: 'oncall@yourdomain.com'
        headers:
          Subject: '[ALERT] {{ .GroupLabels.alertname }}'

route:
  receiver: 'slack-critical'
  group_by: ['alertname', 'cluster']
  group_wait: 10s
  group_interval: 5m
  repeat_interval: 12h
  routes:
    - match:
        severity: critical
      receiver: 'slack-critical'
    - match:
        severity: high
      receiver: 'slack-high'
    - match:
        severity: medium
      receiver: 'email-oncall'
```

## Dashboards

### Grafana Dashboard

Create a Grafana dashboard with these panels:

**Overview:**
- Request rate (requests/second)
- Error rate (%)
- p50, p95, p99 latency
- Requests in progress

**Database:**
- Connection pool utilization
- Query latency histogram
- Queries per second
- Database error rate

**Compiler:**
- Compilations per hour
- Compilation latency
- Compilation failure rate
- AST size distribution

**Security:**
- Auth failures per minute
- Rate limit violations
- Authorization failures

### Example Grafana Queries

**Request Rate:**
```
sum(rate(http_requests_total{job="fraud-governance-api"}[5m]))
```

**Error Rate:**
```
sum(rate(http_errors_total{job="fraud-governance-api"}[5m])) / sum(rate(http_requests_total{job="fraud-governance-api"}[5m]))
```

**p95 Latency:**
```
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="fraud-governance-api"}[5m])) by (le))
```

**Database Pool:**
```
db_pool_checked_out{job="fraud-governance-api"} / db_pool_size{job="fraud-governance-api"}
```

## Platform-Specific Monitoring

### Choreo

Choreo provides built-in monitoring:

1. **Metrics**
   - Go to "Observability" → "Metrics"
   - View request rate, error rate, latency
   - Filter by endpoint and status code

2. **Logs**
   - Go to "Observability" → "Logs"
   - Filter by log level
   - Search by correlation ID

3. **Alerts**
   - Go to "Observability" → "Alerts"
   - Configure thresholds
   - Set up notifications

### AWS CloudWatch

If deploying to AWS App Runner:

1. **Create CloudWatch Dashboard**
   - Go to CloudWatch → Dashboards → Create dashboard
   - Add metrics panels

2. **Create CloudWatch Alarms**
   - Go to CloudWatch → Alarms → Create alarm
   - Select metric and threshold
   - Configure SNS notifications

3. **CloudWatch Logs Insights**
   - Create log groups for application logs
   - Use CloudWatch agent to stream logs
   - Query logs with Insights syntax

## Troubleshooting with Metrics

### High Error Rate

1. **Check error types**
   ```promql
   sum by (error_type) (rate(http_errors_total[5m]))
   ```

2. **Check specific endpoint**
   ```promql
   sum by (route) (rate(http_requests_total{status_code=~"5.."}[5m]))
   ```

3. **Review logs**
   ```
   level:ERROR AND timestamp:[now-15m TO now]
   ```

### High Latency

1. **Check database query time**
   ```promql
   histogram_quantile(0.95, sum(rate(db_query_duration_seconds_bucket[5m])) by (le))
   ```

2. **Check compiler time**
   ```promql
   histogram_quantile(0.95, sum(rate(compiler_duration_seconds_bucket[5m])) by (le))
   ```

3. **Check endpoint breakdown**
   ```promql
   histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, route))
   ```

### Memory Issues

1. **Check memory usage**
   - Platform metrics (Choreo, CloudWatch)
   - Look for gradual increase (memory leak)

2. **Check connection pool**
   ```promql
   db_pool_checked_out / db_pool_size
   ```

3. **Review large queries**
   ```
   # Look for queries returning many records
   db_query_duration_seconds{operation="query_rules"} > 1
   ```

## Best Practices

1. **Set up alerts before you need them**
   - Don't wait for an outage to configure alerting

2. **Use correlation IDs**
   - All requests include `X-Request-ID` header
   - Use this to trace requests across logs

3. **Monitor the right metrics**
   - Focus on user-facing metrics (latency, errors)
   - Avoid alert fatigue (don't alert on everything)

4. **Regular review**
   - Review alert thresholds monthly
   - Adjust based on actual traffic patterns
   - Add new metrics as the system evolves

5. **Document response procedures**
   - For each alert, document the response steps
   - See [Runbooks](runbooks.md) for detailed procedures

---

**Related Documentation:**
- [Production Checklist](../05-deployment/production-checklist.md)
- [Security Hardening](security-hardening.md)
- [Runbooks](runbooks.md)

**Last Updated**: 2026-01-14
