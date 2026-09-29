from __future__ import annotations

import json
from pathlib import Path

KERNEL = Path("evidence/V2.9_GOVERNANCE_KERNEL.json")
FOUNDATION = Path("evidence/V2.9_VALIDITY_AND_DISCIPLINE_FOUNDATION.json")
EXIT_AUDIT = Path("evidence/V2.9_INTEGRITY_EXIT_AUDIT_CONTRACT.json")

REQUIRED_INVARIANTS = {
    "NO_LEAKAGE",
    "NO_SILENT_SAMPLE_MUTATION",
    "NO_UNDOCUMENTED_OVERRIDE",
    "NO_UNSUPPORTED_CERTAINTY",
    "NO_GOAL_DRIFT",
}

REQUIRED_ARCHITECTURE = {
    "GOVERNANCE_KERNEL",
    "EVIDENCE_ENGINE",
    "VALIDITY_ENGINE",
    "DISCIPLINE_ENGINE",
}


def read(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"MISSING_REQUIRED_FILE:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    k = read(KERNEL)
    f = read(FOUNDATION)
    e = read(EXIT_AUDIT)

    if k.get("schema") != "AI_CORE_EVID_V2_9_GOVERNANCE_KERNEL_V1":
        raise RuntimeError("KERNEL_SCHEMA_BLOCK")
    if k.get("status") != "FROZEN_ARCHITECTURE_BASELINE":
        raise RuntimeError("KERNEL_STATUS_BLOCK")

    invariants = set(k.get("constitutional_invariants", {}))
    if invariants != REQUIRED_INVARIANTS:
        raise RuntimeError(f"KERNEL_INVARIANT_DRIFT:{sorted(invariants)}")

    architecture = set(k.get("architecture", {}))
    if architecture != REQUIRED_ARCHITECTURE:
        raise RuntimeError(f"KERNEL_ARCHITECTURE_DRIFT:{sorted(architecture)}")

    compat = k.get("backward_compatibility", {})
    required_compat = {
        "V2_8_12R_evidence_is_immutable": True,
        "V2_8_12R_existing_gates_remain_binding_until_explicitly_closed": True,
        "no_existing_threshold_or_pass_condition_is_changed_by_this_kernel": True,
        "new_kernel_applies_prospectively_to_new_governance_design": True,
    }
    for key, expected in required_compat.items():
        if compat.get(key) is not expected:
            raise RuntimeError(f"BACKWARD_COMPATIBILITY_BLOCK:{key}")

    gate_rule = k.get("gate_admission_test", {}).get("rule", "")
    if "If all answers are NO" not in gate_rule:
        raise RuntimeError("GATE_ADMISSION_RULE_BLOCK")

    if f.get("governance_kernel") != str(KERNEL):
        raise RuntimeError("FOUNDATION_KERNEL_BINDING_BLOCK")
    if e.get("governance_kernel") != str(KERNEL):
        raise RuntimeError("EXIT_AUDIT_KERNEL_BINDING_BLOCK")

    if f.get("status") != "FOUNDATION_FROZEN_BEFORE_IMPLEMENTATION":
        raise RuntimeError("FOUNDATION_STATUS_BLOCK")
    if e.get("status") != "FROZEN_BEFORE_AUDIT":
        raise RuntimeError("EXIT_AUDIT_STATUS_BLOCK")

    result = {
        "schema": "AI_CORE_EVID_V2_9_GOVERNANCE_KERNEL_VALIDATION_V1",
        "status": "PASS",
        "checks": {
            "constitutional_invariants_exact": True,
            "four_module_architecture_exact": True,
            "V2_8_12R_backward_compatibility_preserved": True,
            "gate_admission_rule_present": True,
            "validity_discipline_foundation_bound": True,
            "integrity_exit_audit_bound": True,
        },
        "note": "This validator checks governance structure only. It does not authorize V2.8.12R R2, alter historical gates, or evaluate strategy profitability.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
