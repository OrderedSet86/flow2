"""Phase 3 acceptance tests: diagnostics explain broken/ambiguous input."""

from research.common.corpus import load_case
from research.common.provenance import build_system
from research.q2_diagnostics.iis import find_iis
from research.q2_diagnostics.rank_nullity import analyze


def _bare_system(name, extra_pins=()):
    case = load_case(name, with_externals=False)
    pins = [(p.edge, p.value) for p in case.pins] + list(extra_pins)
    return build_system(case.graph, pins)


def test_undetermined_reports_freedom_group():
    report = analyze(_bare_system('testProjects/undeterminedMultiInput'))
    assert report.consistent
    assert report.nullity == 1
    (group,) = report.freedom_groups
    ingredients = {e[1] for e in group.edges}
    assert 'ammonia' in ingredients          # the two parallel producers
    assert 'you' not in report.human()       # sanity: message is well-formed


def test_loop_graph_bare_system_is_overconstrained():
    """math.md failure mode 1, measured: without externals the lossy loop
    admits no solution at all."""
    report = analyze(_bare_system('testProjects/loopGraph'))
    assert not report.consistent


def test_fully_determined_chart():
    report = analyze(_bare_system('light_fuel_hydrogen_loop'))
    assert report.consistent
    assert report.nullity == 0


def test_iis_names_conflicting_pins():
    case = load_case('testProjects/ab', with_externals=False)
    pins = [(p.edge, p.value) for p in case.pins]
    system_ok = build_system(case.graph, pins)
    other_edge = [e for e in system_ok.edge_to_var if e != case.pins[0].edge][2]
    system_bad = build_system(case.graph, pins + [(other_edge, 123.0)])

    conflict = find_iis(system_bad)
    tags = {c.tag[0] for c in conflict.constraints}
    assert 'pin' in tags, 'the conflicting pins must be named'
    assert len(conflict.constraints) <= 6, 'IIS should be minimal, not the whole chart'
    text = conflict.human()
    assert 'cannot all hold' in text and 'Mitigations' in text
