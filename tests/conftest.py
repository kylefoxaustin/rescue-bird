"""pytest configuration: ensure project root is on sys.path."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens", action="store_true", default=False,
        help="Regenerate golden snapshots instead of asserting against them",
    )
