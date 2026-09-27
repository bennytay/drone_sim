"""Print the versioned Deployment IR JSON Schema."""

import json

from drone_sim.ir import DeploymentIR


def main() -> None:
    print(json.dumps(DeploymentIR.model_json_schema(), indent=2))


if __name__ == "__main__":
    main()
