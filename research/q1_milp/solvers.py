"""Backend-neutral (MI)LP model + adapters for CBC (PuLP), HiGHS, and SCIP.

The model is built once from a provenance.System; each backend translates it,
so benchmarks compare solvers rather than model-building code.
"""

import time
from dataclasses import dataclass, field
from fractions import Fraction


@dataclass
class Row:
    terms: dict          # var -> float coefficient
    sense: str           # '==' | '<=' | '>='
    rhs: float
    name: str = ''


@dataclass
class Model:
    rows: list = field(default_factory=list)
    objective: dict = field(default_factory=dict)   # var -> coeff, minimized
    binaries: set = field(default_factory=set)
    # var -> (lo, hi); default (0, None). None = unbounded.
    bounds: dict = field(default_factory=dict)
    # HiGHS presolve wrongly declares MILPs with a tight cardinality-cap row
    # infeasible (observed on palladium_line stage 2); set by callers that
    # add such rows. Other backends ignore it.
    highs_presolve_off: bool = False

    def add(self, terms, sense, rhs, name=''):
        self.rows.append(Row(dict(terms), sense, float(rhs), name))

    def var_names(self):
        names = {}
        for row in self.rows:
            for v in row.terms:
                names[v] = None
        for v in self.objective:
            names[v] = None
        for v in self.binaries:
            names[v] = None
        for v in self.bounds:
            names[v] = None
        return list(names)

    def bound(self, var):
        lo, hi = self.bounds.get(var, (0.0, None))
        if var in self.binaries:
            lo = 0.0 if lo is None else max(lo, 0.0)
            hi = 1.0 if hi is None else min(hi, 1.0)
        return lo, hi


@dataclass
class Solution:
    status: str            # 'optimal' | 'infeasible' | 'unbounded' | 'other'
    values: dict           # var -> float
    objective: float
    wall_seconds: float
    backend: str


def model_from_system(system, float_coeffs=True) -> Model:
    """Rows are normalized by their largest |coefficient|: recipe quantities
    span ~0.05 (dusts) to ~20000 (fluids), and unscaled ratio rows at that
    spread trip solver tolerances (observed as spurious infeasibility on the
    394-machine nanocircuits case)."""
    model = Model()
    for i, con in enumerate(system.constraints):
        scale = max(abs(c) for _, c in con.terms)
        model.add({v: float(c / scale) for v, c in con.terms},
                  '==', float(con.rhs / scale), name=f'c{i}')
    return model


def validate_solution(system, values, tol=1e-4) -> dict:
    """Plug float values into the exact constraints; return worst violations."""
    worst = {'max_residual': 0.0, 'row': None}
    for con in system.constraints:
        scale = max(abs(float(c)) for _, c in con.terms)
        residual = abs(sum(float(c) * values.get(v, 0.0) for v, c in con.terms)
                       - float(con.rhs)) / scale
        if residual > worst['max_residual']:
            worst = {'max_residual': residual, 'row': con.tag}
    worst['ok'] = worst['max_residual'] <= tol
    return worst


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

def _solve_pulp(model: Model, time_limit, msg) -> Solution:
    import pulp

    prob = pulp.LpProblem('model', pulp.LpMinimize)
    lp_vars = {}
    for name in model.var_names():
        lo, hi = model.bound(name)
        # PuLP's cat='Binary' silently resets bounds to (0, 1), which would
        # discard gate-fixing bounds like (0, 0) — use Integer + explicit bounds.
        cat = 'Integer' if name in model.binaries else 'Continuous'
        lp_vars[name] = pulp.LpVariable(name, lowBound=lo, upBound=hi, cat=cat)

    prob += pulp.lpSum(coeff * lp_vars[v] for v, coeff in model.objective.items())
    for row in model.rows:
        expr = pulp.lpSum(coeff * lp_vars[v] for v, coeff in row.terms.items())
        if row.sense == '==':
            prob += expr == row.rhs, row.name or None
        elif row.sense == '<=':
            prob += expr <= row.rhs, row.name or None
        else:
            prob += expr >= row.rhs, row.name or None

    start = time.perf_counter()
    status_code = prob.solve(pulp.PULP_CBC_CMD(
        msg=msg, timeLimit=time_limit,
        options=['integerTolerance 1e-9', 'primalTolerance 1e-9']))
    wall = time.perf_counter() - start
    status = {1: 'optimal', -1: 'infeasible', -2: 'unbounded'}.get(status_code, 'other')
    values = {name: (var.value() if var.value() is not None else 0.0)
              for name, var in lp_vars.items()}
    return Solution(status, values, pulp.value(prob.objective) or 0.0, wall, 'cbc')


def _solve_highs(model: Model, time_limit, msg) -> Solution:
    import highspy
    import numpy as np

    h = highspy.Highs()
    h.setOptionValue('output_flag', bool(msg))
    # Default 1e-6 integrality tolerance lets a binary sit at ~1e-7 and leak
    # flow through a big-M link ("closed" gate passing M*1e-7 units).
    # 1e-9 would be tighter still, but below HiGHS's primal feasibility
    # tolerance it produces spurious infeasibility (seen on palladium_line).
    h.setOptionValue('mip_feasibility_tolerance', 1e-8)
    if model.highs_presolve_off:
        h.setOptionValue('presolve', 'off')
    if time_limit:
        h.setOptionValue('time_limit', float(time_limit))

    names = model.var_names()
    index = {v: i for i, v in enumerate(names)}
    inf = highspy.kHighsInf

    lower = np.array([model.bound(v)[0] if model.bound(v)[0] is not None else -inf
                      for v in names])
    upper = np.array([model.bound(v)[1] if model.bound(v)[1] is not None else inf
                      for v in names])
    cost = np.array([float(model.objective.get(v, 0.0)) for v in names])
    h.addVars(len(names), lower, upper)
    h.changeColsCost(len(names), np.arange(len(names)), cost)

    for v in model.binaries:
        h.changeColIntegrality(index[v], highspy.HighsVarType.kInteger)

    for row in model.rows:
        idxs = np.array([index[v] for v in row.terms], dtype=np.int32)
        coeffs = np.array(list(row.terms.values()))
        if row.sense == '==':
            lo, hi = row.rhs, row.rhs
        elif row.sense == '<=':
            lo, hi = -inf, row.rhs
        else:
            lo, hi = row.rhs, inf
        h.addRow(lo, hi, len(idxs), idxs, coeffs)

    start = time.perf_counter()
    h.run()
    wall = time.perf_counter() - start

    status_map = {
        highspy.HighsModelStatus.kOptimal: 'optimal',
        highspy.HighsModelStatus.kInfeasible: 'infeasible',
        highspy.HighsModelStatus.kUnbounded: 'unbounded',
        highspy.HighsModelStatus.kTimeLimit: 'timeout',
    }
    status = status_map.get(h.getModelStatus(), 'other')
    sol = h.getSolution()
    values = {v: float(sol.col_value[index[v]]) for v in names} if status == 'optimal' \
        else {v: 0.0 for v in names}
    objective = float(h.getObjectiveValue()) if status == 'optimal' else 0.0
    return Solution(status, values, objective, wall, 'highs')


def _solve_scip(model: Model, time_limit, msg) -> Solution:
    from pyscipopt import Model as ScipModel, quicksum

    scip = ScipModel()
    if not msg:
        scip.hideOutput()
    # See HiGHS note: prevent big-M leakage through near-zero binaries.
    scip.setParam('numerics/feastol', 1e-9)
    if time_limit:
        scip.setParam('limits/time', float(time_limit))

    scip_vars = {}
    for name in model.var_names():
        lo, hi = model.bound(name)
        vtype = 'B' if name in model.binaries else 'C'
        scip_vars[name] = scip.addVar(name=name, vtype=vtype, lb=lo, ub=hi)

    scip.setObjective(
        quicksum(coeff * scip_vars[v] for v, coeff in model.objective.items()),
        'minimize')
    for row in model.rows:
        expr = quicksum(coeff * scip_vars[v] for v, coeff in row.terms.items())
        if row.sense == '==':
            scip.addCons(expr == row.rhs)
        elif row.sense == '<=':
            scip.addCons(expr <= row.rhs)
        else:
            scip.addCons(expr >= row.rhs)

    start = time.perf_counter()
    scip.optimize()
    wall = time.perf_counter() - start

    status = scip.getStatus()
    status = {'optimal': 'optimal', 'infeasible': 'infeasible',
              'unbounded': 'unbounded', 'timelimit': 'timeout'}.get(status, 'other')
    if status == 'optimal':
        sol = scip.getBestSol()
        values = {name: scip.getSolVal(sol, var) for name, var in scip_vars.items()}
        objective = scip.getObjVal()
    else:
        values = {name: 0.0 for name in scip_vars}
        objective = 0.0
    return Solution(status, values, objective, wall, 'scip')


BACKENDS = {
    'cbc': _solve_pulp,
    'highs': _solve_highs,
    'scip': _solve_scip,
}


def solve(model: Model, backend: str = 'highs', time_limit=None, msg=False) -> Solution:
    return BACKENDS[backend](model, time_limit, msg)
