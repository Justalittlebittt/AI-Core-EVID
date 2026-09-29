from pathlib import Path

import v2812r_r2_source_coverage_preflight as impl

RECONCILED_GATE = Path("evidence/retrospective_feasibility/V2.8.12R_R1_TECHNICAL_GATE_RECONCILED_RECEIPT.json")
INITIAL_GATE = Path("evidence/retrospective_feasibility/V2.8.12R_R1_TECHNICAL_GATE_RECEIPT.json")


def main() -> None:
    r = impl.read_json(RECONCILED_GATE)
    i = impl.read_json(INITIAL_GATE)
    if r.get("status") != "R1_COHORT_TECHNICALLY_COMPLETE":
        raise RuntimeError("RECONCILED_R1_GATE_NOT_PASS")
    if r.get("R2_price_or_return_access_authorized") is not True:
        raise RuntimeError("RECONCILED_R2_AUTHORIZATION_BLOCK")
    if r.get("reconciliation_basis", {}).get("initial_gate_receipt") != str(INITIAL_GATE):
        raise RuntimeError("RECONCILIATION_INITIAL_GATE_BINDING_BLOCK")
    if r.get("reconciliation_basis", {}).get("original_gate_receipt_preserved") is not True:
        raise RuntimeError("ORIGINAL_GATE_PRESERVATION_BLOCK")
    if i.get("status") != "R1_TECHNICAL_INCOMPLETE_R2_OUTCOME_ACCESS_BLOCKED":
        raise RuntimeError("HISTORICAL_GATE_STATE_DRIFT")
    if i.get("R2_price_or_return_access_authorized") is not False:
        raise RuntimeError("HISTORICAL_GATE_AUTHORIZATION_DRIFT")
    if r.get("price_or_return_data_consumed_in_R1") is not False:
        raise RuntimeError("R1_PRICE_FIREWALL_BLOCK")

    impl.TECH_GATE = RECONCILED_GATE
    impl.main()


if __name__ == "__main__":
    main()
