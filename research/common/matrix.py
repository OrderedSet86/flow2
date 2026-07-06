"""Exact rational matrix view of a System, for rank/nullspace analysis."""

from fractions import Fraction

import sympy

from research.common.provenance import System


def system_matrix(system: System, include_kinds=('edge',)):
    """Return (A, b, var_order) over sympy Rationals for the constraints whose
    variables are all within `include_kinds` (default: the pure internal
    system, no source/sink columns).

    Constraints that reference excluded variables keep their included columns
    only if every excluded term is dropped safely — for balance rows this
    means analyzing the chart as the user drew it (no externals), so pass a
    System built from a graph without externals for exact semantics.
    """
    var_order = [name for name, info in system.variables.items()
                 if info.kind in include_kinds]
    var_index = {name: i for i, name in enumerate(var_order)}

    rows, rhs = [], []
    for con in system.constraints:
        coeffs = con.coeff_dict()
        if any(name not in var_index for name in coeffs):
            continue
        row = [sympy.Rational(0)] * len(var_order)
        for name, coeff in coeffs.items():
            row[var_index[name]] = sympy.Rational(coeff.numerator, coeff.denominator)
        rows.append(row)
        rhs.append(sympy.Rational(con.rhs.numerator, con.rhs.denominator))

    A = sympy.Matrix(rows) if rows else sympy.Matrix(0, len(var_order), [])
    b = sympy.Matrix(rhs) if rhs else sympy.Matrix(0, 1, [])
    return A, b, var_order


def rank_nullity(system: System, include_kinds=('edge',)):
    A, _, var_order = system_matrix(system, include_kinds)
    rank = A.rank()
    return {'rank': rank,
            'n_vars': len(var_order),
            'nullity': len(var_order) - rank}
