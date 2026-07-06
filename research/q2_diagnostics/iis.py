"""Infeasibility explanation: find a minimal set of conflicting constraints
(an IIS, irreducible infeasible subsystem) and render it via provenance tags
as a mitigation message. This is the principled version of the old
sympy_solver.py line-94 TODO ("binary search over subproblems").

Primary method: deletion filter — O(#constraints) LP feasibility solves,
exact and backend-agnostic. Secondary: Farkas certificate from the HiGHS dual
ray (single solve), when available.
"""

from dataclasses import dataclass

from research.common.provenance import System
from research.q1_milp.solvers import Model, model_from_system, solve


@dataclass
class Conflict:
    constraints: list        # provenance-tagged Constraint objects
    method: str

    def human(self) -> str:
        lines = ['These constraints cannot all hold at once:']
        for con in self.constraints:
            lines.append(f'  - {con.human()}')
        lines.append('Mitigations: remove/adjust one of the recipes above, '
                     'change the pinned rate, or allow an external '
                     'source/sink for the ingredient named in the balance.')
        return '\n'.join(lines)


def _is_feasible(system: System, keep_mask, backend='highs') -> bool:
    model = Model()
    for i, con in enumerate(system.constraints):
        if not keep_mask[i]:
            continue
        scale = max(abs(c) for _, c in con.terms)
        model.add({v: float(c / scale) for v, c in con.terms},
                  '==', float(con.rhs / scale), name=f'c{i}')
    model.objective = {}
    return solve(model, backend).status == 'optimal'


def find_iis(system: System, backend='highs') -> Conflict:
    """Deletion filter. The input system (typically built WITHOUT externals,
    or with gates forced shut) must be infeasible."""
    n = len(system.constraints)
    keep = [True] * n
    assert not _is_feasible(system, keep, backend), 'system is feasible'

    for i in range(n):
        keep[i] = False
        if _is_feasible(system, keep, backend):
            keep[i] = True     # constraint i is necessary for infeasibility
    members = [con for i, con in enumerate(system.constraints) if keep[i]]
    return Conflict(members, 'deletion_filter')


def farkas_certificate(system: System):
    """Best effort: nonzero dual-ray components name the conflicting rows in
    one solve. Returns list of (constraint, weight) or None if unavailable."""
    import highspy
    import numpy as np

    h = highspy.Highs()
    h.setOptionValue('output_flag', False)
    h.setOptionValue('presolve', 'off')   # rays need the unpresolved model

    names, index = [], {}
    for con in system.constraints:
        for v, _ in con.terms:
            if v not in index:
                index[v] = len(names)
                names.append(v)
    inf = highspy.kHighsInf
    h.addVars(len(names), np.zeros(len(names)), np.full(len(names), inf))
    for con in system.constraints:
        scale = max(abs(c) for _, c in con.terms)
        idxs = np.array([index[v] for v, _ in con.terms], dtype=np.int32)
        coeffs = np.array([float(c / scale) for _, c in con.terms])
        rhs = float(con.rhs / scale)
        h.addRow(rhs, rhs, len(idxs), idxs, coeffs)
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kInfeasible:
        return None
    try:
        has_ray, ray = h.getDualRay()
    except Exception:
        return None
    if not has_ray:
        return None
    out = []
    for i, con in enumerate(system.constraints):
        if abs(ray[i]) > 1e-9:
            out.append((con, float(ray[i])))
    return out
