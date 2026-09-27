"""Command-line entry point for local deployment reconstruction."""

from __future__ import annotations

import argparse
from pathlib import Path

from drone_sim.context import ContextOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="Read-only deployment folder")
    parser.add_argument("--state", type=Path, help="Persistent state path outside root")
    parser.add_argument("--output", type=Path, help="Write completed Deployment IR here")
    args = parser.parse_args()

    state_path = args.state or args.root.parent / f"{args.root.name}.state.json"
    deployment, state = ContextOrchestrator(args.root, state_path).run()
    if deployment is None:
        missing = sorted(set(("deployment_id", "vehicle", "mission", "site", "autonomy", "success_criteria")) - state.candidates.keys())
        raise SystemExit(f"Deployment IR incomplete; missing: {', '.join(missing)}")

    rendered = deployment.model_dump_json(indent=2) + "\n"
    if args.output:
        root = args.root.resolve(strict=True)
        if args.output.resolve().is_relative_to(root):
            raise SystemExit("Output path must be outside the read-only deployment folder")
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
