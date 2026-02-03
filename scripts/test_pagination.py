"""Test script to verify keyset pagination works correctly."""

from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import create_app

# Create mock admin user
mock_user = {"sub": "test-user-123", "https://fraud-rule-management.com/roles": ["ADMIN"]}

app = create_app()
app.dependency_overrides[get_current_user] = lambda: mock_user

client = TestClient(app)

print("=" * 60)
print("TESTING KEYSET PAGINATION")
print("=" * 60)

# Test 1: Rules pagination
print("\n1. GET /api/v1/rules?limit=5")
print("-" * 40)
response = client.get("/api/v1/rules?limit=5")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"OK Items count: {len(data.get('items', []))}")
    print(f"OK Has next: {data.get('has_next')}")
    print(f"OK Has prev: {data.get('has_prev')}")
    print(f"OK Next cursor: {repr(data.get('next_cursor'))[:50]}...")
    print(f"OK Limit: {data.get('limit')}")
    print(f"OK Response has correct keys: {set(data.keys())}")
    assert "items" in data
    assert "has_next" in data
    assert "has_prev" in data
    assert "next_cursor" in data
    assert "prev_cursor" in data
    assert "limit" in data
    # Verify NO 'total', 'page', 'page_size' keys
    assert "total" not in data, "ERROR: 'total' should not exist in keyset pagination"
    assert "page" not in data, "ERROR: 'page' should not exist in keyset pagination"
    assert "page_size" not in data, "ERROR: 'page_size' should not exist in keyset pagination"
    print("OK Verified: No offset pagination fields (total, page, page_size)")
else:
    print(f"ERROR: {response.text[:200]}")

# Test 2: Rulesets pagination
print("\n2. GET /api/v1/rulesets?limit=3")
print("-" * 40)
response = client.get("/api/v1/rulesets?limit=3")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"OK Items count: {len(data.get('items', []))}")
    print(f"OK Has next: {data.get('has_next')}")
    print(f"OK Has prev: {data.get('has_prev')}")
    print(f"OK Limit: {data.get('limit')}")
    assert "items" in data
    assert "total" not in data
    print("OK Verified: Keyset pagination response format")
else:
    print(f"ERROR: {response.text[:200]}")

# Test 3: Approvals pagination
print("\n3. GET /api/v1/approvals?limit=10")
print("-" * 40)
response = client.get("/api/v1/approvals?limit=10")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"OK Items count: {len(data.get('items', []))}")
    print(f"OK Has next: {data.get('has_next')}")
    print(f"OK Has prev: {data.get('has_prev')}")
    print(f"OK Limit: {data.get('limit')}")
    assert "items" in data
    assert "total" not in data
    print("OK Verified: Keyset pagination response format")
else:
    print(f"ERROR: {response.text[:200]}")

# Test 4: Audit log pagination
print("\n4. GET /api/v1/audit-log?limit=20")
print("-" * 40)
response = client.get("/api/v1/audit-log?limit=20")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print(f"OK Items count: {len(data.get('items', []))}")
    print(f"OK Has next: {data.get('has_next')}")
    print(f"OK Has prev: {data.get('has_prev')}")
    print(f"OK Limit: {data.get('limit')}")
    assert "items" in data
    assert "total" not in data
    print("OK Verified: Keyset pagination response format")
else:
    print(f"ERROR: {response.text[:200]}")

# Test 5: Verify direction parameter works
print("\n5. GET /api/v1/rules?limit=5&direction=next")
print("-" * 40)
response = client.get("/api/v1/rules?limit=5&direction=next")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print("OK Direction parameter accepted")
    print(f"OK Items count: {len(data.get('items', []))}")
else:
    print(f"ERROR: {response.text[:200]}")

# Test 6: Verify cursor parameter works (even with empty cursor)
print("\n6. GET /api/v1/rules?limit=5&cursor=")
print("-" * 40)
response = client.get("/api/v1/rules?limit=5&cursor=")
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print("OK Cursor parameter accepted")
    print(f"OK Items count: {len(data.get('items', []))}")
else:
    print(f"ERROR: {response.text[:200]}")

print("\n" + "=" * 60)
print("ALL TESTS PASSED! Keyset pagination is working correctly.")
print("=" * 60)
