# Solver benchmark (zero-config lexicographic MILP)

All charts solved with target pins only, uniform weights, all-machines-run floors where needed. Interactive budget: 15s per stage; over budget = DNF.

Cell format: gates / machines-running / wall / validated. "floors dropped" = the backend could not solve the all-machines-run MILP in budget and fell back to the honest floor-free answer (fewer gates, idle machines).

| case | machines | cbc | highs | scip |
|---|---|---|---|---|
| 230_platline | 28 | 1 / 28m / 0.19s / yes | 2 / 28m / 0.06s / yes | 1 / 28m / 0.10s / yes |
| cetane | 9 | 0 / 9m / 0.02s / yes | 0 / 9m / 0.02s / yes | 0 / 9m / 0.01s / yes |
| jet_fuel | 10 | 2 / 10m / 0.03s / yes | 2 / 10m / 0.02s / yes | 2 / 10m / 0.02s / yes |
| light_fuel | 3 | 0 / 3m / 0.01s / yes | 0 / 3m / 0.01s / yes | 0 / 3m / 0.01s / yes |
| light_fuel_hydrogen_loop | 3 | 0 / 3m / 0.01s / yes | 0 / 3m / 0.01s / yes | 0 / 3m / 0.01s / yes |
| microsheep | 2 | 0 / 2m / 0.01s / yes | 0 / 2m / 0.01s / yes | 0 / 2m / 0.01s / yes |
| mk1 | 2 | 1 / 2m / 0.01s / yes | 1 / 2m / 0.02s / yes | 1 / 2m / 0.01s / yes |
| nanocircuits | 394 | 0 / 394m / 0.35s / NO | 0 / 394m / 0.49s / yes | 0 / 394m / 0.19s / yes |
| palladium | 5 | 0 / 5m / 0.02s / NO | 0 / 5m / 0.01s / yes | 0 / 5m / 0.01s / yes |
| palladium_line | 56 | DNF (other, 30.4s) | 11 / 56m / 1.40s / yes | 3 / 1m / 15.62s / yes (floors dropped) |
| twoslack | 2 | 1 / 2m / 0.02s / yes | 1 / 2m / 0.01s / yes | 1 / 2m / 0.01s / yes |
| testProjects/ab | 3 | 0 / 3m / 0.02s / yes | 0 / 3m / 0.01s / yes | 0 / 3m / 0.01s / yes |
| testProjects/loopGraph | 2 | 1 / 2m / 0.02s / yes | 1 / 2m / 0.01s / yes | 1 / 2m / 0.01s / yes |
| testProjects/sideLockedMultiInput | 4 | 0 / 4m / 0.02s / yes | 0 / 4m / 0.02s / yes | 0 / 3m / 0.01s / yes (floors dropped) |
| testProjects/simpleGraph | 2 | 0 / 2m / 0.01s / yes | 0 / 2m / 0.01s / yes | 0 / 2m / 0.01s / yes |
| testProjects/undeterminedMultiInput | 3 | 0 / 3m / 0.02s / yes | 0 / 3m / 0.01s / yes | 0 / 3m / 0.01s / yes |
