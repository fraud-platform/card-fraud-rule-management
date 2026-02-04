import json

from app.main import app

openapi = app.openapi()
with open("docs/03-api/openapi.json", "w", encoding="utf-8") as f:
    json.dump(openapi, f, indent=2, ensure_ascii=False)
print("Wrote docs/03-api/openapi.json")
