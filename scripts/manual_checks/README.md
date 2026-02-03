# Manual Checks

These scripts are quick/manual validation helpers.
They are **not** part of automated pytest discovery.

Run examples:

```powershell
doppler run --project=card-fraud-rule-management --config=local -- uv run python scripts/manual_checks/check_auth_integration.py
doppler run --project=card-fraud-rule-management --config=local -- uv run python scripts/manual_checks/check_telemetry_setup.py
```
