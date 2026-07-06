"""Four-stage lexicographic MILP for zero-config flow solving.

Stage 0 (MILP): maximize the NUMBER of machines that run. The user placed
    every machine deliberately (in PlanNH, physically on a canvas); a
    solution that idles machines to save a source is the math.md
    "pull 2 of A instead of 1000 of B" degeneracy resurfacing at the
    subgraph level (observed: palladium_line "solved" by running 2 of its
    56 machines from a bootstrap source). Maximizing binary UTILIZATION is
    bounded, unlike math.md's flow-maximization attempt, so positive-feedback
    loops cannot blow it up.
Stage 1 (MILP): minimize the number of active source/sink nodes on
    intermediate ingredients (uniform weights — no curated lists).
Stage 2 (MILP, count capped): minimize total external quantity. Kills the
    quantity-level degeneracy: zeroing a chain would need extra active
    sources, already forbidden by stage 1.
Stage 3 (LP, gates fixed): minimize total internal flow. Pins the free
    circulation of fully-recycling loops to its minimum.

Two hard-won correctness details (see research.md):
- Gate support is derived from the actual external FLOWS of each stage's
  solution, never from the binary values: with big-M links, a binary within
  integrality tolerance of 0 can still pass M*tol units of flow ("leak"),
  and a binary at 1 with zero flow is a free gate that later stages would
  exploit to reroute around the chain.
- Stage 3 only runs with the gates that carried flow in stage 2; otherwise
  "minimize flow" rediscovers the degenerate dump-to-sink solutions.
"""

import math
from dataclasses import dataclass

from research.common.provenance import System
from research.q1_milp.solvers import Model, Solution, model_from_system, solve

DEFAULT_M = 1e6
QTY_EPS = 1e-7      # relative slack on the stage-2 quantity cap in stage 3
ZERO = 1e-6         # flows below this count as zero when deriving support
USE_EPS = 1e-4          # fallback pass-2 floor scale (crafts/s)
USE_EPS_DETECT = 1e-7   # a machine "runs" if its crafts/s exceeds this
# Interactive-tool budget (user feedback): >60s is useless, real patience is
# ~20s. Each stage gets a slice; an over-budget stage returns 'timeout'.
STAGE_TIME_LIMIT = 15.0

# Structural (not curated) tiebreak: a sink means "discard the excess", which
# the player can always do; a source means "supply this intermediate from
# outside", a new obligation. Weight sources one epsilon-step heavier so
# equal-count solutions prefer sinks. Integer weights (1024/1025 rather than
# 1/1.001) keep every objective value exactly representable — fractional
# weights in the stage-2 count-cap row made HiGHS presolve declare spurious
# infeasibility. Count dominates as long as #sources < 1024.
SNK_WEIGHT = 1024.0
SRC_TIEBREAK = 1.0


@dataclass
class LexResult:
    status: str                 # 'optimal' | 'infeasible' | ...
    values: dict                # var -> float (final stage values)
    gated_sources: list         # intermediate ingredients with an active source
    gated_sinks: list           # intermediate ingredients with an active sink
    terminal_sources: list      # (ingredient, qty) for ungated externals
    terminal_sinks: list
    source_count: int           # |gated sources| + |gated sinks|  (stage 1)
    external_quantity: float    # stage-2 objective value
    total_flow: float           # stage-3 objective value
    stage_walls: dict
    big_m: float
    backend: str
    leak_detected: bool = False  # FINAL solution passes flow through a closed gate
    machines_total: int = 0     # machines in the chart
    machines_used: int = 0      # machines running in the solution (stage 0)
    idle_machines: list = None  # (node_idx, machine_name) left idle
    floors_used: bool = False   # solved with the all-machines-run floors
    # False when an intermediate stage's solution leaked through a closed
    # gate (big-M * integrality tolerance window): the final answer is still
    # honest, but the gate-count optimality certificate is weakened.
    count_certified: bool = True
    # The machine floors actually applied (ref edge var -> lower bound), or
    # None. Enumeration must reuse these to stay consistent with the solve.
    floors: dict = None


def _gate_map(system: System):
    gates = {}
    for ing in system.intermediates():
        entry = {}
        for info in system.variables.values():
            if info.ingredient == ing and info.kind in ('src', 'snk'):
                entry[info.kind] = info.name
        if entry:
            if 'src' in entry:
                entry['y_src'] = f'y_src[{ing}]'
            if 'snk' in entry:
                entry['y_snk'] = f'y_snk[{ing}]'
            gates[ing] = entry
    return gates


def _base_model(system: System, gates: dict, big_m: float) -> Model:
    model = model_from_system(system)
    for ing, gate in gates.items():
        for kind, y_kind in (('src', 'y_src'), ('snk', 'y_snk')):
            if kind in gate:
                model.binaries.add(gate[y_kind])
                model.add({gate[kind]: 1.0, gate[y_kind]: -big_m}, '<=', 0.0,
                          name=f'link_{kind}[{ing}]')
    return model


def _flow_support(gates: dict, values: dict) -> dict:
    """y variable name -> 0/1 from the flows actually carried."""
    support = {}
    for gate in gates.values():
        for kind, y_kind in (('src', 'y_src'), ('snk', 'y_snk')):
            if kind in gate:
                support[gate[y_kind]] = 1 if values.get(gate[kind], 0.0) > ZERO else 0
    return support


def _machine_refs(system: System) -> dict:
    """machine node idx -> a reference edge variable. The ratio rows make all
    of a machine's edges proportional, so any one edge witnesses 'running'."""
    refs = {}
    for info in system.variables.values():
        if info.kind == 'edge' and info.machine_idx is not None:
            refs.setdefault(info.machine_idx, info.name)
    return refs


def solve_lexicographic(system: System, backend: str = 'highs',
                        big_m: float = DEFAULT_M, msg: bool = False,
                        max_m_growths: int = 3,
                        prefer_sinks: bool = True,
                        use_all_machines: bool = True,
                        gate_support: dict = None) -> LexResult:
    """gate_support: optional {'sources': [ing...], 'sinks': [ing...]} from
    enumerate_optimal_supports — pins stage 1 to that user-chosen support so
    stages 2-3 optimize within the chosen alternative."""
    gates = _gate_map(system)
    external = system.external_vars()
    internal = [v.name for v in system.variables.values() if v.kind == 'edge']
    gated_vars = {gate[k] for gate in gates.values() for k in ('src', 'snk')
                  if k in gate}
    refs = _machine_refs(system)
    walls = {'stage1': 0.0}

    # ---- Stage 0: prefer every machine running, WITHOUT distorting flows.
    # Implemented as per-machine LOWER BOUNDS on the reference edge, not
    # binaries: an explicit maximize-machines-used MILP needs link rows whose
    # coefficients (1e-4 .. 1e6 against big-M) break solvers outright (HiGHS
    # kSolveError on palladium_line). Bounds never enter the constraint
    # matrix.
    #
    # A FIXED floor is not scale-free: on light_fuel a 1e-4 crafts/s floor
    # exceeded the electrolyzer's natural 8.3e-5 crafts/s rate, forced excess
    # hydrogen through the reactor, and conjured a phantom sulfuric-light-
    # fuel source. So: pass 1 solves floor-free; if every machine already
    # runs (the common case), floors are never applied. Only when machines
    # idle (the bootstrap degeneracy) does pass 2 apply floors, scaled to
    # pass 1's smallest observed running rate so they cannot bind above a
    # plausible natural rate.
    floors_active = False
    machine_floors = {}

    def _per_craft(m_idx, var_name):
        info = system.variables[var_name]
        if -1 in info.edge:
            return 1.0     # extent formulation: the variable IS crafts/s
        nobj = system.graph.nodes[m_idx]['object']
        if info.edge[1] == m_idx:      # ingredient -> machine (input)
            return float(nobj.I[info.ingredient])
        return float(nobj.O[info.ingredient])

    per_craft_ref = {ref: _per_craft(m_idx, ref) for m_idx, ref in refs.items()}

    def crafts_rate(values, ref):
        return values.get(ref, 0.0) / per_craft_ref[ref]

    def set_floors_from(values):
        """Pass-2 floors: 1000x below the smallest rate a machine actually
        ran at in the floor-free solution."""
        running = [crafts_rate(values, ref) for ref in refs.values()
                   if crafts_rate(values, ref) > USE_EPS_DETECT]
        eps = (min(running) if running else USE_EPS) * 1e-3
        machine_floors.clear()
        machine_floors.update({ref: qty * eps
                               for ref, qty in per_craft_ref.items()})

    def add_machine_floor(model):
        if floors_active:
            for ref, floor in machine_floors.items():
                model.bounds[ref] = (floor, None)

    def stage1_weights():
        weights = {}
        for gate in gates.values():
            if 'y_src' in gate:
                weights[gate['y_src']] = SNK_WEIGHT + (SRC_TIEBREAK if prefer_sinks else 0.0)
            if 'y_snk' in gate:
                weights[gate['y_snk']] = SNK_WEIGHT
        return weights

    # ---- Stage 1: minimize number of active intermediate sources/sinks
    def solve_stage1(start_m):
        s1, attempt_m = None, start_m
        for _ in range(max_m_growths + 1):
            model = _base_model(system, gates, attempt_m)
            add_machine_floor(model)
            model.objective = stage1_weights()
            s1 = solve(model, backend, time_limit=STAGE_TIME_LIMIT, msg=msg)
            walls['stage1'] += s1.wall_seconds
            if s1.status == 'timeout':
                break             # over budget: growing M won't help
            if s1.status != 'optimal':
                # An M too small makes gated-but-needed flow impossible, which
                # also presents as infeasibility — retry larger first.
                attempt_m *= 10
                continue
            if any(s1.values.get(v, 0.0) > 0.9 * attempt_m for v in gated_vars):
                attempt_m *= 10   # a gated flow is pressed against the cap
                continue
            break
        return s1, attempt_m

    fixed_gate_bounds = None
    if gate_support is not None:
        fixed_gate_bounds = {}
        for ing, gate in gates.items():
            if 'y_src' in gate:
                fixed_gate_bounds[gate['y_src']] = \
                    1.0 if ing in gate_support.get('sources', ()) else 0.0
            if 'y_snk' in gate:
                fixed_gate_bounds[gate['y_snk']] = \
                    1.0 if ing in gate_support.get('sinks', ()) else 0.0

    if fixed_gate_bounds is None:
        s1, big_m = solve_stage1(big_m)      # pass 1: floor-free
        if s1.status == 'optimal' and use_all_machines and refs:
            idle = [ref for ref in refs.values()
                    if crafts_rate(s1.values, ref) <= USE_EPS_DETECT]
            if idle:
                # Bootstrap degeneracy: retry with scaled floors (pass 2).
                set_floors_from(s1.values)
                floors_active = True
                s1_floored, m_floored = solve_stage1(big_m)
                if s1_floored.status == 'optimal':
                    s1, big_m = s1_floored, m_floored
                else:
                    floors_active = False    # keep honest pass-1 result
        if s1.status != 'optimal':
            return LexResult(s1.status, s1.values, [], [], [], [], -1,
                             math.nan, math.nan, walls, big_m, backend,
                             machines_total=len(refs), floors_used=floors_active)

        support1 = _flow_support(gates, s1.values)
        count = sum(support1.values())
        # Certification check: the solver claimed a better objective than the
        # support its own flows used — an intermediate big-M/tolerance leak.
        expected_obj = sum(stage1_weights()[y] for y, on in support1.items() if on)
        certified = s1.objective >= expected_obj - 0.5
    else:
        count = int(sum(fixed_gate_bounds.values()))
        certified = True

    # ---- Stage 2: minimize external quantity. Normally binaries are free
    # with the (weighted) count capped at the stage-1 optimum — a true
    # lexicographic stage picking the least external flow among minimal-count
    # placements. With a user-chosen gate_support, the binaries are fixed to
    # that support instead.
    model = _base_model(system, gates, big_m)
    model.highs_presolve_off = True
    add_machine_floor(model)
    if fixed_gate_bounds is None:
        model.add(stage1_weights(), '<=', s1.objective + 0.5, name='count_cap')
    else:
        for y, val in fixed_gate_bounds.items():
            model.bounds[y] = (val, val)
    model.objective = {v: 1.0 for v in external}
    s2 = solve(model, backend, time_limit=STAGE_TIME_LIMIT, msg=msg)
    walls['stage2'] = s2.wall_seconds
    if s2.status == 'optimal' and fixed_gate_bounds is not None \
            and use_all_machines and refs and not floors_active:
        # Fixed-support path skipped stage 1, so run the two-pass floor
        # logic here: without it a chosen alternative could bring back the
        # bootstrap degeneracy (idle machines).
        if any(crafts_rate(s2.values, ref) <= USE_EPS_DETECT
               for ref in refs.values()):
            set_floors_from(s2.values)
            floors_active = True
            model = _base_model(system, gates, big_m)
            model.highs_presolve_off = True
            add_machine_floor(model)
            for y, val in fixed_gate_bounds.items():
                model.bounds[y] = (val, val)
            model.objective = {v: 1.0 for v in external}
            s2_floored = solve(model, backend, time_limit=STAGE_TIME_LIMIT,
                               msg=msg)
            walls['stage2'] += s2_floored.wall_seconds
            if s2_floored.status == 'optimal':
                s2 = s2_floored
            else:
                floors_active = False
    if s2.status != 'optimal':
        return LexResult(s2.status, s2.values, [], [], [], [], count,
                         math.nan, math.nan, walls, big_m, backend,
                         count_certified=certified)
    quantity = s2.objective
    certified = certified and (
        sum(_flow_support(gates, s2.values).values()) <= count)

    # ---- Stage 3: gates re-fixed to stage-2 flow support, cap quantity,
    #      minimize total internal flow
    support = _flow_support(gates, s2.values)
    model = _base_model(system, gates, big_m)
    model.highs_presolve_off = True
    add_machine_floor(model)
    for y, val in support.items():
        model.bounds[y] = (float(val), float(val))
    model.add({v: 1.0 for v in external}, '<=',
              quantity * (1 + QTY_EPS) + QTY_EPS, name='qty_cap')
    model.objective = {v: 1.0 for v in internal}
    s3 = solve(model, backend, time_limit=STAGE_TIME_LIMIT, msg=msg)
    walls['stage3'] = s3.wall_seconds
    if s3.status != 'optimal':
        return LexResult(s3.status, s2.values, [], [], [], [], count, quantity,
                         math.nan, walls, big_m, backend,
                         count_certified=certified)

    gated_sources, gated_sinks = [], []
    terminal_sources, terminal_sinks = [], []
    leak_final = False
    for info in sorted(system.variables.values(), key=lambda i: i.name):
        if info.kind not in ('src', 'snk'):
            continue
        qty = s3.values.get(info.name, 0.0)
        if qty <= ZERO:
            continue
        if info.name in gated_vars:
            (gated_sources if info.kind == 'src' else gated_sinks).append(
                info.ingredient)
            y_kind = 'y_src' if info.kind == 'src' else 'y_snk'
            if not support.get(gates[info.ingredient][y_kind], 0):
                leak_final = True   # flow through a gate stage 3 held shut
        else:
            (terminal_sources if info.kind == 'src' else terminal_sinks).append(
                (info.ingredient, qty))

    used_final = {m_idx: crafts_rate(s3.values, ref) > USE_EPS_DETECT
                  for m_idx, ref in refs.items()}
    idle = [(m_idx, system.graph.nodes[m_idx]['object'].m)
            for m_idx, used in sorted(used_final.items()) if not used]
    return LexResult('optimal', s3.values, gated_sources, gated_sinks,
                     terminal_sources, terminal_sinks,
                     len(gated_sources) + len(gated_sinks),
                     quantity, s3.objective, walls, big_m, backend, leak_final,
                     machines_total=len(refs),
                     machines_used=sum(used_final.values()),
                     idle_machines=idle, floors_used=floors_active,
                     count_certified=certified,
                     floors=dict(machine_floors) if floors_active else None)


def edge_values(system: System, result: LexResult) -> dict:
    """(u, v) graph edge -> solved flow value."""
    return {info.edge: result.values.get(info.name, 0.0)
            for info in system.variables.values()}
