"""Exact rank/nullity analysis of the chart as the user drew it (no
externals): how many degrees of freedom exist, and which edges move together.

Zero-config role: the MILP absorbs this freedom automatically; this module
QUANTIFIES what was absorbed and powers human messages when genuine ambiguity
survives (see research.md Q2).
"""

from dataclasses import dataclass

import sympy

from research.common.corpus import Case, load_case
from research.common.matrix import system_matrix
from research.common.provenance import System, build_system


@dataclass
class FreedomGroup:
    """One degree of freedom: the set of edges that scale together."""
    edges: list          # (var, ingredient, machine_idx, direction) tuples


@dataclass
class RankReport:
    n_vars: int
    rank: int
    nullity: int
    consistent: bool             # equality system has any solution (sign-free)
    negative_forced: list        # vars < 0 in every solution (need a source)
    freedom_groups: list         # list[FreedomGroup]

    def human(self) -> str:
        lines = []
        if not self.consistent:
            lines.append('The chart is over-constrained: no flow assignment '
                         'satisfies every recipe ratio and balance. Run the '
                         'conflict finder (iis.py) for the minimal culprit set.')
            return '\n'.join(lines)
        if self.nullity == 0:
            lines.append('The chart is fully determined by its pins.')
        else:
            lines.append(
                f'The chart has {self.nullity} degree(s) of freedom beyond '
                f'the pins; the solver resolves them by minimizing external '
                f'sources/sinks, then external quantity, then total flow.')
            for i, group in enumerate(self.freedom_groups):
                names = ', '.join(sorted({e[1] for e in group.edges}))
                lines.append(f'  freedom {i + 1}: flows of [{names}] scale together')
        if self.negative_forced:
            names = ', '.join(sorted({v[1] for v in self.negative_forced}))
            lines.append(
                f'Balance would force negative flow for [{names}] — these '
                f'need an external source (the solver adds one).')
        return '\n'.join(lines)


def analyze(case_or_system, pins=None) -> RankReport:
    """Accepts a corpus Case (analyzed without externals) or a prebuilt
    System."""
    if isinstance(case_or_system, System):
        system = case_or_system
    else:
        case = case_or_system
        bare = load_case(case.name, with_externals=False)
        system = build_system(bare.graph,
                              [(p.edge, p.value) for p in bare.pins])

    A, b, var_order = system_matrix(system, include_kinds=('edge',))
    aug = A.row_join(b)
    rank = A.rank()
    consistent = aug.rank() == rank
    nullity = len(var_order) - rank

    freedom_groups = []
    if consistent and nullity:
        for basis_vec in A.nullspace():
            edges = []
            for i, val in enumerate(basis_vec):
                if val != 0:
                    info = system.variables[var_order[i]]
                    direction = 'in' if info.edge[1] == info.machine_idx else 'out'
                    edges.append((info.name, info.ingredient,
                                  info.machine_idx, direction))
            freedom_groups.append(FreedomGroup(edges))

    negative_forced = []
    if consistent:
        # Particular solution + nullspace: a variable is forced negative if
        # its value is < 0 in the least-squares particular solution and no
        # nullspace direction can raise it while keeping others >= 0. Exact
        # minimal check is an LP; here we do the cheap certain case:
        # nullity == 0 and the unique solution has negative entries.
        if nullity == 0 and rank == len(var_order):
            solution = A.solve(b)
            for i, val in enumerate(solution):
                if val < 0:
                    info = system.variables[var_order[i]]
                    negative_forced.append((info.name, info.ingredient))

    return RankReport(len(var_order), rank, nullity, consistent,
                      negative_forced, freedom_groups)
