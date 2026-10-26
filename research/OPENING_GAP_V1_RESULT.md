# Opening-gap reversion — first real-data result (2026-10-26)

**Research disposition: NOT SUPPORTED. Do not promote to candidate screening or trading.**

This is the first result for the precommitted distinct hypothesis in [EXPLORATORY_OPENING_GAP_V1.json](EXPLORATORY_OPENING_GAP_V1.json), committed before any outcomes were computed in this experiment (`05939c7`). No thresholds, directions, cost assumptions, selection fractions or date ranges were changed after result inspection. A second runner execution corrected **only the CSI300 benchmark date-key type**; it did not change selection or returns. Both historical runs' logs remain inspectable.

**Verified GitHub Actions:** [final run 40266339601](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40266339601), job PASS including synthetic invariants, pinned historic dataset processing, and artifact upload. [Prior run 40266211119](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40266211119) initially omitted CSI300 comparison due to datetime/date key mismatch; research results against equal-weight A shares were unchanged.

## Fixed test and observed result

- Signal: 10% of PIT-active A shares with lowest `open(D)/close(previous joint session)-1` at day D close. Future outcomes were not used for selecting signals.
- Primary descriptive outcome: D close to D+5 joint A-share trading day close, subtract **assumed** 0.3% round-trip transaction cost.
- Observations: 409 signal days; 210,693 selected security-date events; 210,250 observed D+5 outcomes (**99.7897%** coverage). Overlapping five-session events are **not** independent portfolio returns.
- Average selected **net** five-session return, equally averaging daily cross-sectional means: **-0.3577%**.
- Average same-day all-eligible-universe equal-weight gross five-session return: **+0.4975%**.
- **Mean selected-minus-universe excess: -0.8552 percentage points per five-session signal day.**
- **Mean selected-minus-CSI300 excess: -0.5882 percentage points.**
- 2025 development: 242 days; selected-minus-universe mean **-0.8448 pp**.
- 2026 chronological check (not untouched OOS): 167 days; selected-minus-universe mean **-0.8702 pp**.
- All seven observed calendar-quarter mean excess values were negative.

The recorded average full-universe return is gross, while selected return is net of illustrative costs, exactly as specified in the experiment contract. Outcome missingness and possible execution/price-adjustment limits remain; no executable portfolio return or statistical alpha significance was established. Prior use of overlapping historical windows means the 2026 partition must not be advertised as pristine OOS.

**Decision:** Hypothesis is not supported. **Do not** reverse the signal or adjust parameters post hoc and claim independent validation. No candidate promotion, no STRONG/MODERATE strength, no BUY permission. Continue the main product route by assessing a separately preregistered hypothesis or real position-monitoring requirements, not by fixing this negative result.

## Evidence references

- Contract: `research/EXPLORATORY_OPENING_GAP_V1.json`, contract SHA256 `c8d8bfaeac40c8d45719da8a3ee52d1c054d766075cff22ca8dfe8592a4fe609`.
- Source stock parquet SHA256 `acb8ae5e31f58fe3972455b86614d668837f18afd59126c505faaae06920954b`.
- CSI300 benchmark SHA256 `75c4fba2de6875e125c539187fdf7e44eae90d740fce64907f8ce8df6ff58234`.
- PIT ledger SHA256 `52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1`.
- Detailed daily report retained as [GitHub Actions artifact](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40266339601) with finite retention. This permanent summary preserves the decision even if artifact expires.
- No Fold3/Fold4, V2.8.12 prospective return consumption, frozen-gate edits or live-trade authorization.
