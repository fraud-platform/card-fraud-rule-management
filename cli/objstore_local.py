#!/usr/bin/env python3
"""
Local MinIO Object Storage Management

Provides uv scripts for managing the local MinIO container.
Checks for shared platform infrastructure first (card-fraud-platform),
falls back to local docker-compose if not available.

Usage:
    uv run objstore-local-up: Start MinIO with Doppler secrets
    uv run objstore-local-down: Stop MinIO
    uv run objstore-local-reset: Stop MinIO and remove data
    uv run objstore-local-verify: Verify MinIO setup and list buckets
"""

import subprocess
import sys

from cli._runner import run

# Container name (matches shared platform)
MINIO_CONTAINER = "card-fraud-minio"


def _is_platform_container_running() -> bool:
    """Check if the shared platform MinIO container is already running."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Status}}", MINIO_CONTAINER],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "running"


def up() -> int:
    """Start MinIO container using Doppler secrets."""
    if _is_platform_container_running():
        print(f"[OK] MinIO already running via shared platform ({MINIO_CONTAINER})")
        print("     Managed by: card-fraud-platform")
        print("     API: http://localhost:9000  Console: http://localhost:9001")
        return 0

    return run(
        [
            "doppler",
            "run",
            "--config",
            "local",
            "--",
            "docker",
            "compose",
            "-f",
            "docker-compose.local.yml",
            "up",
            "-d",
            "minio",
            "minio-mc-init",
        ]
    )


def down() -> int:
    """Stop MinIO containers without removing data."""
    if _is_platform_container_running():
        print(f"[INFO] MinIO is managed by card-fraud-platform ({MINIO_CONTAINER})")
        print("       To stop: cd ../card-fraud-platform && uv run platform-down")
        return 0

    return run(
        ["docker", "compose", "-f", "docker-compose.local.yml", "stop", "minio", "minio-mc-init"]
    )


def reset() -> int:
    """Stop MinIO containers and remove all data."""
    return run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.local.yml",
            "rm",
            "-f",
            "-v",
            "minio",
            "minio-mc-init",
        ]
    )


def infra_up() -> int:
    """Start all local infrastructure (PostgreSQL + MinIO)."""
    if _is_platform_container_running():
        print("[OK] Infrastructure already running via shared platform")
        print("     Managed by: card-fraud-platform")
        return 0

    return run(
        [
            "doppler",
            "run",
            "--config",
            "local",
            "--",
            "docker",
            "compose",
            "-f",
            "docker-compose.local.yml",
            "up",
            "-d",
        ]
    )


def infra_down() -> int:
    """Stop all local infrastructure."""
    return run(["docker", "compose", "-f", "docker-compose.local.yml", "down"])


def verify() -> int:
    """Verify MinIO setup and list buckets.

    Usage:
        uv run objstore-local-verify
    """
    import json

    print("\u001b[1mVerifying MinIO S3-compatible storage...\u001b[0m")

    # Import boto3 inside the function so it only runs when needed
    try:
        import boto3
    except ImportError:
        print("\u001b[91m[ERROR]\u001b[0m boto3 not installed. Run: uv pip install boto3")
        return 1

    # Check if MinIO is running (platform or local)
    print("\u001b[1m[1/4] Checking MinIO container status...\u001b[0m")
    if _is_platform_container_running():
        print(f"\u001b[92m[OK]\u001b[0m MinIO running via shared platform ({MINIO_CONTAINER})")
    else:
        result = subprocess.run(
            ["docker", "compose", "-f", "docker-compose.local.yml", "ps", "minio"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or "minio" not in result.stdout:
            print("\u001b[91m[ERROR]\u001b[0m MinIO container is not running")
            print("   Start via platform: cd ../card-fraud-platform && uv run platform-up")
            print("   Start locally:      uv run objstore-local-up")
            return 1
        print(f"\u001b[92m[OK]\u001b[0m MinIO running via local compose ({MINIO_CONTAINER})")

    # Get environment variables from Doppler
    print("\u001b[1m[2/4] Fetching MinIO credentials from Doppler...\u001b[0m")

    try:
        result = subprocess.run(
            [
                "doppler",
                "run",
                "--config",
                "local",
                "--",
                "python",
                "-c",
                "import os; import json; print(json.dumps({"
                "'S3_ENDPOINT_URL': os.environ.get('S3_ENDPOINT_URL'), "
                "'S3_ACCESS_KEY_ID': os.environ.get('S3_ACCESS_KEY_ID'), "
                "'S3_SECRET_ACCESS_KEY': os.environ.get('S3_SECRET_ACCESS_KEY'), "
                "'S3_BUCKET_NAME': os.environ.get('S3_BUCKET_NAME'), "
                "'S3_REGION': os.environ.get('S3_REGION', 'us-east-1'), "
                "'S3_FORCE_PATH_STYLE': os.environ.get('S3_FORCE_PATH_STYLE', 'true')"
                "}))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse JSON from output (skip any warning lines)
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                s3_config = json.loads(line)
                break
        else:
            raise ValueError("No JSON found in Doppler output")

    except Exception as e:
        print(f"\u001b[91m[ERROR]\u001b[0m Failed to fetch credentials: {e}")
        return 1

    print("\u001b[92m[OK]\u001b[0m Credentials loaded from Doppler")

    # Test S3 connection
    print("\u001b[1m[3/4] Testing S3 connection...\u001b[0m")
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=s3_config["S3_ENDPOINT_URL"],
            aws_access_key_id=s3_config["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=s3_config["S3_SECRET_ACCESS_KEY"],
            region_name=s3_config["S3_REGION"],
        )
        # List buckets to verify connection
        response = s3.list_buckets()
        print("\u001b[92m[OK]\u001b[0m S3 connection successful")
    except Exception as e:
        print(f"\u001b[91m[ERROR]\u001b[0m S3 connection failed: {e}")
        return 1

    # List buckets and verify expected bucket exists
    print("\u001b[1m[4/4] Verifying buckets...\u001b[0m")
    buckets = [bucket["Name"] for bucket in response["Buckets"]]
    print(f"\u001b[92m[OK]\u001b[0m Found {len(buckets)} bucket(s):")
    for bucket in buckets:
        print(f"   - {bucket}")

    expected_bucket = s3_config["S3_BUCKET_NAME"]
    if expected_bucket in buckets:
        print(f"\u001b[92m[OK]\u001b[0m Expected bucket '{expected_bucket}' exists")

        # Check bucket contents
        try:
            objects = s3.list_objects_v2(Bucket=expected_bucket)
            count = objects.get("KeyCount", 0)
            print(f"\u001b[92m[OK]\u001b[0m Bucket '{expected_bucket}' contains {count} object(s)")

            if count > 0 and "Contents" in objects:
                print("   Objects:")
                for obj in objects["Contents"][:5]:  # Show first 5 objects
                    size_kb = obj["Size"] / 1024
                    print(f"     - {obj['Key']} ({size_kb:.2f} KB)")
                if count > 5:
                    print(f"     ... and {count - 5} more object(s)")
        except Exception as e:
            print(f"\u001b[94m[INFO]\u001b[0m Could not list bucket contents: {e}")

    else:
        print(f"\u001b[91m[WARNING]\u001b[0m Expected bucket '{expected_bucket}' not found")
        print("   The bucket will be created automatically when needed")

    print("\u001b[1m" + "=" * 60 + "\u001b[0m")
    print("\u001b[92m\u001b[1mMINIO SETUP VERIFIED\u001b[0m")
    print("\u001b[1m" + "=" * 60 + "\u001b[0m")
    print("\nMinIO Console: http://localhost:9001")
    print(f"S3 Endpoint: {s3_config['S3_ENDPOINT_URL']}")
    print(f"Region: {s3_config['S3_REGION']}")
    print("\nNext steps:")
    print("  - View MinIO Console: Open http://localhost:9001 in browser")
    print("  - Upload test object: uv run python -c '...'")
    print("  - Stop MinIO: uv run objstore-local-down")

    return 0


def main() -> int:
    """Default entry point - starts MinIO."""
    return up()


if __name__ == "__main__":
    sys.exit(main())
