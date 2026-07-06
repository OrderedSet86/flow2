# Case study: palladium line, zero-config

- Chart size: 56 machines, 341 flow variables, 207 constraints.
- User input: **1 pin** (palladium dust = 1/s). No whitelists, no weights, no v2 options.

## What the old workflow needed (commit d86e99b, June 2024)

11 hand-picked `whitelisted_slack_variables`:

> PMP, chlorine, calcium dust, hydrogen, oxygen, nitrogen, carbon dust, potassium dust, sodium dust, salt, sulfur dust

The user had to know, before solving, which ingredients were allowed to be imbalanced — exactly the a-priori slack selection this research set out to remove.

## What the chart actually requires (exact arithmetic)

Without external sources/sinks the chart is **infeasible** (rank 183 augmented-rank mismatch): no assignment of flows satisfies every recipe ratio and conservation law at once. External injection/disposal is mathematically necessary, not a modeling convenience.

## What the MILP found, zero-config

- Status: **optimal**, validated max residual 5.77e-13.
- Machines running: **56/56**.
- Gated externals: **11** — sources ['palladium metallic powder dust', 'PMP', 'calcium chloride dust', 'reprecipitated palladium dust', 'sodium sulfate dust'], sinks ['sodium ruthenate dust', 'sulfur dust', 'crude rhodium metal dust', 'rhodium salt dust', 'sodium hydroxide dust', 'sodium dust'].
- Terminal inputs (raw materials, free): [('saltpeter', 0.057), ('carbon dust', 2.0), ('nitrogen', 1.0)]
- Terminal outputs (products/byproducts, free): [('platinum dust', 0.055), ('iridium dust', 0.017), ('nickel dust', 0.009), ('copper dust', 0.009), ('osmium dust', 0.002), ('palladium dust', 1.0), ('rhodium dust', 0.002), ('ethylene', 500.0), ('ruthenium dust', 0.038), ('gold dust', 0.007)]
- Solve time: 1.30s ({'stage1': 0.241, 'stage2': 1.055, 'stage3': 0.007}) — within the ~20s interactive budget (HiGHS; CBC and SCIP blow the budget on this chart and are disqualified).

The hand-picked whitelist is replaced by automatically-placed externals covering the same structural needs (hydrogen/oxygen makeup, residue disposal), discovered with no user input.

## Why utilization comes first

Without the all-machines-run floor (stage 0), pure count-minimization "solves" this chart with 3 externals by idling 54 of the 56 machines and bootstrapping the final reactor from a source — the math.md "pull 2 of A instead of 1000 of B" degeneracy resurfacing at the subgraph level. Requiring every user-placed machine to run is the structural fix, and unlike math.md's flow-maximization attempt it cannot be exploited by positive-feedback loops (utilization is binary and bounded).

## Known degeneracy

Equal-count gate choices can tie (e.g. sourcing an ingredient vs its 1:1 precursor). The lexicographic quantity stage breaks most ties; the enumeration pass (Phase 2) surfaces the rest so a UI can present the choice.