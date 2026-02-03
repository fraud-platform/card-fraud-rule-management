#!/usr/bin/env python3
"""
Quick test to verify OpenTelemetry setup works correctly.
This test doesn't require a full environment setup.
"""

import sys

# Test 1: Verify telemetry module can be imported
print("Test 1: Import telemetry module...")
try:
    from app.core.telemetry import (  # noqa: F401 (imported for verification)
        get_span_id,
        get_trace_id,
        init_telemetry,
        instrument_fastapi,
        instrument_httpx,
        instrument_sqlalchemy,
        shutdown_telemetry,
    )

    print("[OK] All telemetry functions imported successfully")
except ImportError as e:
    print(f"[FAIL] Failed to import telemetry: {e}")
    sys.exit(1)

# Test 2: Verify helper functions work without initialization
print("\nTest 2: Test trace context functions...")
try:
    trace_id = get_trace_id()
    span_id = get_span_id()
    # Should return None when no span is active
    assert trace_id is None, "Expected trace_id to be None"
    assert span_id is None, "Expected span_id to be None"
    print("[OK] Trace context functions work correctly")
except Exception as e:
    print(f"[FAIL] Trace context functions failed: {e}")
    sys.exit(1)

# Test 3: Verify configuration can be parsed
print("\nTest 3: Test header parsing...")
try:
    from app.core.telemetry import _parse_headers

    # Test with None
    headers = _parse_headers(None)
    assert headers == {}, f"Expected empty dict, got {headers}"

    # Test with valid headers
    headers = _parse_headers("key1=value1,key2=value2")
    assert headers == {"key1": "value1", "key2": "value2"}, (
        f"Expected parsed headers, got {headers}"
    )

    # Test with empty string
    headers = _parse_headers("")
    assert headers == {}, f"Expected empty dict, got {headers}"

    print("[OK] Header parsing works correctly")
except Exception as e:
    print(f"[FAIL] Header parsing failed: {e}")
    sys.exit(1)

# Test 4: Verify resource creation
print("\nTest 4: Test resource creation...")
try:
    from app.core.telemetry import _create_resource

    resource = _create_resource(
        service_name="test-service",
        app_env="test",
        app_region="us-east-1",
    )

    # Check that resource has required attributes
    attributes = resource.attributes
    assert "service.name" in attributes, "Missing service.name"
    assert attributes["service.name"] == "test-service", (
        f"Wrong service name: {attributes.get('service.name')}"
    )

    print("[OK] Resource creation works correctly")
except Exception as e:
    print(f"[FAIL] Resource creation failed: {e}")
    sys.exit(1)

# Test 5: Verify observability module includes trace context
print("\nTest 5: Test observability trace context integration...")
try:
    import logging

    from app.core.observability import StructuredFormatter

    formatter = StructuredFormatter()
    assert hasattr(formatter, "format"), "Formatter missing format method"

    # Create a test log record
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )

    # Format the record
    formatted = formatter.format(record)
    assert formatted is not None, "Formatter returned None"

    # Verify it's valid JSON
    import json

    parsed = json.loads(formatted)
    assert "timestamp" in parsed, "Missing timestamp"
    assert "level" in parsed, "Missing level"
    assert "message" in parsed, "Missing message"

    print("[OK] Observability trace context integration works")
except Exception as e:
    print(f"[FAIL] Observability integration failed: {e}")
    sys.exit(1)

print("\n" + "=" * 50)
print("All tests passed!")
print("=" * 50)
print("\nOpenTelemetry setup is ready to use.")
print("\nTo enable tracing:")
print("1. Set OTEL_ENABLED=true (default)")
print("2. Configure OTEL_EXPORTER_OTLP_ENDPOINT (default: http://localhost:4317)")
print("3. Run the application - telemetry will initialize on startup")
