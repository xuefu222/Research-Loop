"""Launch Research Loop from this repository's Codex skill."""

import sys
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parents[4]
    if not (project_root / "research_loop" / "__main__.py").is_file():
        sys.exit("Run this script from a complete paper-research-skill checkout.")

    sys.path.insert(0, str(project_root))
    from research_loop.__main__ import main as run_cli

    return run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
