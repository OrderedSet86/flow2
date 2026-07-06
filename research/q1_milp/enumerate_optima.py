"""Enumerate ALL count-optimal gate supports via no-good cuts.

UX rationale: equal-count (and even equal-quantity) optima are real — e.g.
palladium_line can source `formic acid` or its 1:1 precursor
`carbon monoxide` interchangeably. A tool should present such choices, not
pick silently.
"""

from research.common.provenance import System
from research.q1_milp.lexicographic import (
    STAGE_TIME_LIMIT, ZERO, _base_model, _flow_support, _gate_map, DEFAULT_M,
    SNK_WEIGHT, SRC_TIEBREAK)
from research.q1_milp.solvers import solve


def enumerate_optimal_supports(system: System, backend: str = 'highs',
                               big_m: float = DEFAULT_M, max_solutions: int = 10,
                               prefer_sinks: bool = True,
                               floors: dict = None) -> list:
    # max_solutions=10 per user feedback: ONE prompt with up to ~10 choices
    # is acceptable UX; anything beyond that should not be asked.
    """Return every gate support achieving the stage-1 optimum, as
    [{'sources': [...], 'sinks': [...]}] in discovery order.

    floors: pass LexResult.floors so enumeration runs under the same
    all-machines-run conditions as the solve — otherwise it enumerates the
    floor-free (bootstrap) optima, which have a different gate count."""
    gates = _gate_map(system)

    weights = {}
    for gate in gates.values():
        if 'y_src' in gate:
            weights[gate['y_src']] = SNK_WEIGHT + (SRC_TIEBREAK if prefer_sinks else 0.0)
        if 'y_snk' in gate:
            weights[gate['y_snk']] = SNK_WEIGHT

    cuts = []
    best_obj = None
    solutions = []
    while len(solutions) < max_solutions:
        model = _base_model(system, gates, big_m)
        model.highs_presolve_off = True
        for ref, floor in (floors or {}).items():
            model.bounds[ref] = (floor, None)
        model.objective = dict(weights)
        for i, support in enumerate(cuts):
            # forbid this exact support: sum_{on}(1-y) + sum_{off} y >= 1
            terms = {}
            rhs = 1.0
            for y, on in support.items():
                if on:
                    terms[y] = -1.0
                    rhs -= 1.0
                else:
                    terms[y] = 1.0
            model.add(terms, '>=', rhs, name=f'nogood{i}')
        result = solve(model, backend, time_limit=STAGE_TIME_LIMIT)
        if result.status != 'optimal':
            break
        if best_obj is None:
            best_obj = result.objective
        elif result.objective > best_obj + 0.5:
            break     # next-best support costs strictly more: done

        support = _flow_support(gates, result.values)
        # Guard against tolerance leaks producing a "cheaper" phantom support.
        expected = sum(weights[y] for y, on in support.items() if on)
        if expected > result.objective + 0.5:
            break
        cuts.append(support)
        by_ing = {'sources': [], 'sinks': []}
        for ing, gate in sorted(gates.items()):
            if support.get(gate.get('y_src', ''), 0):
                by_ing['sources'].append(ing)
            if support.get(gate.get('y_snk', ''), 0):
                by_ing['sinks'].append(ing)
        solutions.append(by_ing)
    return solutions
