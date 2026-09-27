"""Print the versioned evidence-backed Deployment IR JSON Schema."""

import json

from drone_sim.provenance import EvidenceBackedDeployment


def main() -> None:
    print(json.dumps(EvidenceBackedDeployment.model_json_schema(), indent=2))


if __name__ == "__main__":
    main()
