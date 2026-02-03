param(
  [int]$Port = 8000
)

# Loads env vars from env.example-like files is intentionally not automated here.
# On Windows, set env vars in your session:
#   $env:DATABASE_URL_APP = "..."

uv run uvicorn app.main:app --host 0.0.0.0 --port $Port --reload
