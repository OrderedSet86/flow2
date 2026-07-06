"""Solver benchmark: corpus x backends -> research/q1_milp/bench_results.md.
Run: uv run python -m research.q1_milp.bench
"""

import time
from pathlib import Path

from research.common.corpus import list_cases, load_case
from research.common.provenance import build_system
from research.q1_milp.lexicographic import solve_lexicographic
from research.q1_milp.solvers import validate_solution

BACKENDS = ['cbc', 'highs', 'scip']
OUT = Path(__file__).with_name('bench_results.md')


def main():
    lines = ['# Solver benchmark (zero-config lexicographic MILP)',
             '',
             'All charts solved with target pins only, uniform weights, '
             'all-machines-run floors where needed. Interactive budget: '
             '15s per stage; over budget = DNF.',
             '',
             'Cell format: gates / machines-running / wall / validated. '
             '"floors dropped" = the backend could not solve the '
             'all-machines-run MILP in budget and fell back to the honest '
             'floor-free answer (fewer gates, idle machines).',
             '',
             '| case | machines | ' +
             ' | '.join(f'{b}' for b in BACKENDS) + ' |',
             '|---|---|' + '---|' * len(BACKENDS)]
    for name in list_cases():
        case = load_case(name)
        pins = [(p.edge, p.value) for p in case.pins]
        system = build_system(case.graph, pins)
        cells = []
        machines = None
        for backend in BACKENDS:
            t0 = time.perf_counter()
            r = solve_lexicographic(system, backend=backend)
            wall = time.perf_counter() - t0
            machines = r.machines_total
            if r.status != 'optimal':
                cells.append(f'DNF ({r.status}, {wall:.1f}s)')
                continue
            ok = validate_solution(system, r.values)['ok']
            cell = (f'{r.source_count} / {r.machines_used}m / {wall:.2f}s / '
                    f'{"yes" if ok else "NO"}')
            if r.machines_used < r.machines_total:
                cell += ' (floors dropped)'
            cells.append(cell)
        lines.append(f'| {name} | {machines} | ' + ' | '.join(cells) + ' |')
        print(lines[-1])
    OUT.write_text('\n'.join(lines) + '\n')
    print(f'\nwrote {OUT}')


if __name__ == '__main__':
    main()
