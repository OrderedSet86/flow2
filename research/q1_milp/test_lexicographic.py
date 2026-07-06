"""Acceptance tests for the zero-config lexicographic MILP (research plan
Phase 1). Run: uv run pytest research/ -q
"""

import math

import pytest

from research.common.corpus import list_cases, load_case
from research.common.matrix import rank_nullity
from research.common.provenance import build_system
from research.q1_milp.lexicographic import solve_lexicographic, edge_values
from research.q1_milp.solvers import validate_solution

BACKENDS = ['cbc', 'highs', 'scip']
# Findings, not bugs here (see research.md): CBC returns a solution violating
# conservation by ~0.08 on the 394-machine nanocircuits case; CBC and SCIP
# blow the interactive time budget on palladium_line once the all-machines
# floors are active (HiGHS solves it in ~2s).
KNOWN_BAD = {('nanocircuits', 'cbc'), ('palladium', 'cbc'),
             ('palladium_line', 'cbc'), ('palladium_line', 'scip')}


def _solve(name, backend='highs', **kw):
    case = load_case(name)
    system = build_system(case.graph, [(p.edge, p.value) for p in case.pins])
    return system, solve_lexicographic(system, backend=backend, **kw)


# ---------------------------------------------------------------------------
# The two math.md failure modes, exact expectations
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('backend', BACKENDS)
def test_loop_graph_needs_exactly_one_source(backend):
    """Non-fully-recycling loop: 2/3 of the sulfuric acid recycles, so 1/3 of
    the loop demand must be injected — no DAG-forcing, no manual slack."""
    case = load_case('testProjects/loopGraph')
    pin_rate = case.pins[0].value        # diluted sulfuric acid into the DT
    system, r = _solve('testProjects/loopGraph', backend)
    assert r.status == 'optimal'
    assert r.source_count == 1
    assert r.gated_sources == ['diluted sulfuric acid']
    assert r.gated_sinks == []
    src_vars = [v.name for v in system.variables.values()
                if v.kind == 'src' and v.ingredient == 'diluted sulfuric acid']
    injected = sum(r.values[v] for v in src_vars)
    assert injected == pytest.approx(pin_rate / 3, rel=1e-6)
    assert validate_solution(system, r.values)['ok']


def test_light_fuel_matches_ground_truth_chart():
    """User-supplied ground truth (gtnh-flow v1 chart): a correct light fuel
    chart has ONLY oil (+ water, removed as ignorable) as input and light
    fuel + oxygen + hydrogen sulfide as outputs. In particular there must be
    NO external sulfuric light fuel — the distillery satisfies it. This
    regression once failed three ways at once: dropped electrolyzer ratio
    coupling after water removal, wrong 'number' pin scale, and a
    non-scale-free machine floor."""
    system, r = _solve('light_fuel', 'highs')
    assert r.status == 'optimal'
    assert r.source_count == 0, 'no gated externals at all'
    assert r.machines_used == r.machines_total == 3
    term_src = dict(r.terminal_sources)
    term_snk = dict(r.terminal_sinks)
    assert set(term_src) == {'oil'}
    assert term_src['oil'] == pytest.approx(25.0)
    assert set(term_snk) == {'light fuel', 'oxygen', 'hydrogen sulfide'}
    assert term_snk['light fuel'] == pytest.approx(25.0)
    assert term_snk['oxygen'] == pytest.approx(25 / 12, rel=1e-6)
    assert term_snk['hydrogen sulfide'] == pytest.approx(25 / 12, rel=1e-6)


def test_light_fuel_hydrogen_loop_fully_recycles():
    """The hydrogen-loop variant recycles H2S back into hydrogen at exactly
    the consumed ratio: zero gated externals, sulfur as the only byproduct."""
    system, r = _solve('light_fuel_hydrogen_loop', 'highs')
    assert r.status == 'optimal'
    assert r.source_count == 0
    assert dict(r.terminal_sources).keys() == {'oil'}
    assert set(dict(r.terminal_sinks)) == {'light fuel', 'sulfur dust'}


@pytest.mark.parametrize('backend', BACKENDS)
def test_mk1_parallel_outputs_prefers_discarding_excess(backend):
    """Parallel-output mismatch: heavy naquadah fuel is overproduced. Two
    count-1 optima exist (sink heavy vs source light); the structural
    prefer-sinks tiebreak must deterministically pick the sink."""
    system, r = _solve('mk1', backend)
    assert r.status == 'optimal'
    assert r.source_count == 1
    assert r.gated_sources == []
    assert r.gated_sinks == ['heavy naquadah fuel']
    assert validate_solution(system, r.values)['ok']


def test_mk1_source_option_exists_without_tiebreak():
    """Without prefer_sinks, quantity minimization picks the globally
    cheaper source-light solution — documenting the alternative optimum."""
    system, r = _solve('mk1', 'highs', prefer_sinks=False)
    assert r.status == 'optimal'
    assert r.source_count == 1
    assert (r.gated_sources, r.gated_sinks) in [
        (['light naquadah fuel'], []),          # cheaper total external qty
        ([], ['heavy naquadah fuel']),          # equally valid count-1 pick
    ]


# ---------------------------------------------------------------------------
# Zero-config contract across the whole corpus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('backend', BACKENDS)
@pytest.mark.parametrize('name', list_cases())
def test_corpus_solves_zero_config(name, backend):
    if (name, backend) in KNOWN_BAD:
        pytest.xfail('CBC solution quality on 394-machine model')
    system, r = _solve(name, backend)
    assert r.status == 'optimal', f'{name} did not solve zero-config'
    assert not r.leak_detected
    assert validate_solution(system, r.values)['ok']
    # target pins must be honored exactly
    case = load_case(name)
    for pin in case.pins:
        var = system.edge_to_var[pin.edge]
        assert r.values[var] == pytest.approx(pin.value, rel=1e-6)


def test_palladium_line_zero_config_summary():
    """The historical 11-manual-inputs case: one target pin now suffices.
    All 56 machines run and the solver auto-places the externals the user
    historically had to whitelist by hand."""
    system, r = _solve('palladium_line', 'highs')
    assert r.status == 'optimal'
    assert r.machines_used == r.machines_total == 56
    assert r.floors_used
    # Poetically, the same count as the historical hand-picked whitelist.
    assert r.source_count == 11
    assert sum(r.stage_walls.values()) < 20.0, 'interactive budget'


def test_palladium_line_without_floors_is_the_bootstrap_degeneracy():
    """Documents WHY stage 0 exists: without the all-machines floors,
    count-minimization 'solves' the chart by idling 54 of 56 machines and
    bootstrapping from a source — math.md's degeneracy at subgraph level."""
    system, r = _solve('palladium_line', 'highs', use_all_machines=False)
    assert r.status == 'optimal'
    assert r.source_count == 3
    assert r.machines_used < 10


def test_nanocircuits_scale_and_balance():
    """394 machines: solves in well under 5 s, all machines running, and
    needs zero gated externals (the chart fully balances)."""
    system, r = _solve('nanocircuits', 'highs')
    assert r.status == 'optimal'
    assert r.source_count == 0
    assert r.machines_used == r.machines_total == 394
    assert sum(r.stage_walls.values()) < 5.0
    assert validate_solution(system, r.values)['ok']


# ---------------------------------------------------------------------------
# Formulation invariants
# ---------------------------------------------------------------------------

def test_star_and_pairwise_forms_agree():
    """Star form (|I|+|O|-1 rows) must have the same solution set as the
    pairwise form (|I|*|O| rows): same rank, and each solution validates
    against the other's constraints."""
    case = load_case('light_fuel_hydrogen_loop')
    pins = [(p.edge, p.value) for p in case.pins]
    star = build_system(case.graph, pins, 'star')
    pair = build_system(case.graph, pins, 'pairwise')
    assert rank_nullity(star) == rank_nullity(pair)
    r = solve_lexicographic(star, backend='highs')
    assert validate_solution(pair, r.values)['ok']


@pytest.mark.parametrize('name', ['testProjects/loopGraph', 'mk1', 'jet_fuel'])
def test_backends_agree_on_count(name):
    counts = set()
    for backend in BACKENDS:
        _, r = _solve(name, backend)
        assert r.status == 'optimal'
        counts.add(r.source_count)
    assert len(counts) == 1, f'backends disagree on gated count for {name}'
