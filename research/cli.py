"""Tinkering CLI for the zero-config MILP solver + layout.

    uv run python -m research.cli <chart.yaml | corpus-name> [options]

Examples:
    uv run python -m research.cli temporaryFlowProjects/230_platline.yaml
    uv run python -m research.cli 230_platline --lead PMP --engine ogdf
    uv run python -m research.cli my_chart.yaml --auto-subgraphs --no-interactive

Solves the chart (one target pin is enough), reports what was placed, offers
enumerated same-quality alternatives (at most one prompt, per UX rule),
renders SVG+PNG.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from research.common.corpus import load_case
from research.common.provenance import build_system
from research.q1_milp.enumerate_optima import enumerate_optimal_supports
from research.q1_milp.lexicographic import solve_lexicographic
from research.q1_milp.solvers import validate_solution
from research.q2_diagnostics.rank_nullity import analyze
from research.q3_layout.interchange import build_graph_json
from research.q3_layout.render import to_svg

ENGINES = {
    'elk': ('research.q3_layout.engines.elk_engine', ['layered', 'orthogonal']),
    'dot': ('research.q3_layout.engines.dot_engine', ['layered']),
    'ogdf': ('research.q3_layout.engines.ogdf_engine', ['layered', 'orthogonal']),
    'grandalf': ('research.q3_layout.engines.grandalf_engine', ['layered']),
}


def summarize(result, check):
    print(f'\n== solve: {result.status} | machines {result.machines_used}/'
          f'{result.machines_total} | gated externals {result.source_count} '
          f'| validated max residual {check["max_residual"]:.1e}')
    if result.gated_sources:
        print(f'   sources: {", ".join(result.gated_sources)}')
    if result.gated_sinks:
        print(f'   sinks:   {", ".join(result.gated_sinks)}')
    if result.terminal_sources:
        pretty = ', '.join(f'{i} {q:.4g}/s' for i, q in result.terminal_sources)
        print(f'   inputs:  {pretty}')
    if result.terminal_sinks:
        pretty = ', '.join(f'{i} {q:.4g}/s' for i, q in result.terminal_sinks)
        print(f'   outputs: {pretty}')
    if result.idle_machines:
        names = ', '.join(m for _, m in result.idle_machines)
        print(f'   ! idle machines (could not run): {names}')
    if result.leak_detected or not result.count_certified:
        print('   ! numerical caveat: gate count not fully certified')


def choose_alternative(supports, current):
    """One prompt, <= 10 options (user UX rule). Returns a support or None."""
    print(f'\n{len(supports)} equally-optimal gate placements exist:')
    for i, s in enumerate(supports):
        parts = []
        if s['sources']:
            parts.append('source ' + ', '.join(s['sources']))
        if s['sinks']:
            parts.append('sink ' + ', '.join(s['sinks']))
        marker = ' (current)' if (s['sources'], s['sinks']) == current else ''
        print(f'  [{i}] {" | ".join(parts) or "(none)"}{marker}')
    reply = input('pick [number, or enter to keep current]: ').strip()
    if reply.isdigit() and int(reply) < len(supports):
        return supports[int(reply)]
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('chart', help='yaml path or corpus name')
    parser.add_argument('--engine', choices=ENGINES, default='elk')
    parser.add_argument('--style', choices=['layered', 'orthogonal'],
                        default='orthogonal')
    parser.add_argument('--backend', choices=['highs', 'cbc', 'scip'],
                        default='highs')
    parser.add_argument('--lead', metavar='NAME',
                        help='primary input to pin at the top (e.g. PMP)')
    parser.add_argument('--auto-subgraphs', action='store_true',
                        help='EXPERIMENTAL: assign subgraphs by unique '
                             'backwards reachability from sinks '
                             '(overrides yaml group: names)')
    parser.add_argument('--no-groups', action='store_true',
                        help='ignore yaml group: names')
    parser.add_argument('--no-interactive', action='store_true',
                        help='never prompt; keep the deterministic default')
    parser.add_argument('--theme', choices=['dark', 'light'], default='dark',
                        help='render theme (default: dark)')
    parser.add_argument('--out', metavar='DIR', default='flow_out',
                        help='output directory (default: ./flow_out)')
    args = parser.parse_args(argv)

    if args.style not in ENGINES[args.engine][1]:
        parser.error(f'{args.engine} does not support --style {args.style}')

    case = load_case(args.chart)
    pins = [(p.edge, p.value) for p in case.pins]
    if not pins:
        print('warning: no target/number pin in the yaml — '
              'the all-zero solution is optimal; pin something.')
    system = build_system(case.graph, pins)

    result = solve_lexicographic(system, backend=args.backend)
    if result.status != 'optimal':
        print(f'solve failed: {result.status}')
        bare = load_case(args.chart, with_externals=False)
        report = analyze(build_system(bare.graph,
                                      [(p.edge, p.value) for p in bare.pins]))
        print(report.human())
        return 1
    check = validate_solution(system, result.values)
    summarize(result, check)

    if not args.no_interactive and result.source_count > 0:
        # prefer_sinks=False so tiebreak-level alternatives (sink excess vs
        # source an intermediate) count as ties and show up in the list.
        supports = enumerate_optimal_supports(system, backend=args.backend,
                                              floors=result.floors,
                                              prefer_sinks=False)
        if len(supports) > 1:
            chosen = choose_alternative(
                supports, (result.gated_sources, result.gated_sinks))
            if chosen is not None:
                result = solve_lexicographic(system, backend=args.backend,
                                             gate_support=chosen)
                check = validate_solution(system, result.values)
                summarize(result, check)

    graph_json = build_graph_json(case, system, result, lead=args.lead,
                                  use_yaml_groups=not args.no_groups,
                                  auto_subgraphs=args.auto_subgraphs)
    if args.auto_subgraphs:
        grouped = [n for n in graph_json['nodes'] if n.get('group')]
        n_groups = len({n['group'] for n in grouped})
        coverage = 100 * len(grouped) / max(len(graph_json['nodes']), 1)
        print(f'\nauto-subgraphs: {n_groups} clusters, '
              f'{coverage:.0f}% coverage '
              f'(sanity envelope: 6-15 clusters, >=80%)')

    import importlib
    engine_mod = importlib.import_module(ENGINES[args.engine][0])
    layout = engine_mod.layout(graph_json, args.style)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(case.path).stem
    svg_path = out_dir / f'{stem}_{args.engine}_{args.style}.svg'
    svg_path.write_text(to_svg(layout, graph_json,
                               f'{case.name} — {args.engine} {args.style}',
                               theme=args.theme))
    png_path = svg_path.with_suffix('.png')
    png_ok = subprocess.run(['convert', str(svg_path), str(png_path)],
                            capture_output=True).returncode == 0
    print(f'\nwrote {svg_path}' + (f' and {png_path}' if png_ok else
                                   ' (png conversion unavailable)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
