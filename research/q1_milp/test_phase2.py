"""Phase 2 acceptance tests: optima enumeration + extent formulation."""

import pytest

from research.common.corpus import load_case
from research.common.provenance import build_system
from research.q1_milp.enumerate_optima import enumerate_optimal_supports
from research.q1_milp.formulation_extent import (build_extent_system,
                                                 derived_edge_flows)
from research.q1_milp.lexicographic import solve_lexicographic
from research.q1_milp.solvers import validate_solution


def _pins(name):
    case = load_case(name)
    return case, [(p.edge, p.value) for p in case.pins]


def test_loop_graph_has_exactly_two_optima():
    """math.md: "I could have also added additional diluted sulfuric acid."
    The enumerator finds exactly those two supports, programmatically."""
    case, pins = _pins('testProjects/loopGraph')
    system = build_system(case.graph, pins)
    sols = enumerate_optimal_supports(system, prefer_sinks=False)
    assert len(sols) == 2
    assert {frozenset(s['sources']) for s in sols} == {
        frozenset({'sulfuric acid'}), frozenset({'diluted sulfuric acid'})}


def test_mk1_has_exactly_the_two_mathmd_alternatives():
    """math.md: discard heavy naquadah OR source light naquadah fuel."""
    case, pins = _pins('mk1')
    system = build_system(case.graph, pins)
    sols = enumerate_optimal_supports(system, prefer_sinks=False)
    assert len(sols) == 2
    shapes = {(tuple(s['sources']), tuple(s['sinks'])) for s in sols}
    assert shapes == {((), ('heavy naquadah fuel',)),
                      (('light naquadah fuel',), ())}


@pytest.mark.parametrize('name', ['light_fuel', 'light_fuel_hydrogen_loop',
                                  'mk1', 'jet_fuel', 'cetane',
                                  'testProjects/loopGraph', 'nanocircuits'])
def test_extent_formulation_matches_edge_formulation(name):
    """Variant B (one extent variable per machine) must reproduce Variant A's
    gate count and edge flows on floor-free cases."""
    case, pins = _pins(name)
    sysA = build_system(case.graph, pins)
    sysB = build_extent_system(case.graph, pins)
    rA = solve_lexicographic(sysA, backend='highs')
    rB = solve_lexicographic(sysB, backend='highs')
    assert rA.status == rB.status == 'optimal'
    assert rA.source_count == rB.source_count
    assert validate_solution(sysB, rB.values)['ok']
    if rA.floors_used or rB.floors_used:
        return   # floor scale differs between formulations; flows may too
    flowsA = {i.edge: rA.values.get(i.name, 0.0)
              for i in sysA.variables.values()}
    flowsB = derived_edge_flows(sysB, rB.values)
    for edge, value in flowsA.items():
        if edge[0] >= 0 and edge[1] >= 0:
            assert flowsB.get(edge, 0.0) == pytest.approx(value, abs=1e-5), edge
