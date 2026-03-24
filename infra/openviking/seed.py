"""
One-time seed script — loads initial Resources and Skills into OpenViking.
Run once after `docker compose up openviking`:

    python infra/openviking/seed.py

Safe to re-run — existing resources are overwritten, not duplicated.
"""
import os
import sys
from pathlib import Path

OPENVIKING_URL = os.environ.get("OPENVIKING_URL", "http://localhost:1933")
OPENVIKING_API_KEY = os.environ.get("OPENVIKING_API_KEY", "")

RESOURCES_DIR = Path(__file__).parent / "resources"
SKILLS_DIR = Path(__file__).parent / "skills"


def seed() -> None:
    try:
        import openviking as ov
    except ImportError:
        print("ERROR: openviking package not installed. Run: pip install openviking")
        sys.exit(1)

    client = ov.SyncHTTPClient(
        url=OPENVIKING_URL,
        api_key=OPENVIKING_API_KEY or None,
    )
    client.initialize()

    total = 0

    # Seed Resources
    for md_file in sorted(RESOURCES_DIR.glob("**/*.md")):
        uri = f"viking://resources/{md_file.stem}/"
        content = md_file.read_text(encoding="utf-8")
        client.add_resource(uri=uri, content=content, metadata={"source": str(md_file.name)})
        print(f"  [resource] {uri}")
        total += 1

    # Seed Skills
    for md_file in sorted(SKILLS_DIR.glob("**/*.md")):
        uri = f"viking://agent/skills/{md_file.stem}/"
        content = md_file.read_text(encoding="utf-8")
        client.add_resource(uri=uri, content=content, metadata={"source": str(md_file.name)})
        print(f"  [skill]    {uri}")
        total += 1

    print(f"\nSeeded {total} documents into OpenViking at {OPENVIKING_URL}")


if __name__ == "__main__":
    seed()
