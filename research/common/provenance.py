"""Neutral constraint representation shared by the MILP solvers (Q1) and the
exact-arithmetic diagnostics (Q2).

Every constraint carries a provenance tag so that solver output and
infeasibility explanations can be rendered in terms the user understands
("machine 3's ratio", "balance of sulfuric acid") instead of matrix rows.

Variable naming convention (strings, stable across runs):
    x{n}      flow on an internal edge (machine <-> ingredient)
    src{n}    flow from the external source of an ingredient
    snk{n}    flow into the external sink of an ingredient
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional, Union

import networkx as nx

from src.data.basicTypes import ExternalNode, IngredientNode, MachineNode

Number = Union[int, float, Fraction]


def to_frac(value: Number) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    # YAML floats like 0.95 / 112.5 are decimal literals; str() round-trips
    # them so Fraction gets the intended decimal, not the binary expansion.
    return Fraction(str(value))


@dataclass(frozen=True)
class Constraint:
    # var name -> exact coefficient; constraint is sum(coeff * var) == rhs
    terms: tuple  # tuple[tuple[str, Fraction], ...] for hashability
    rhs: Fraction
    tag: tuple

    def coeff_dict(self) -> dict:
        return dict(self.terms)

    def human(self) -> str:
        kind = self.tag[0]
        if kind == 'machine_ratio':
            _, m_idx, m_name, ref, other = self.tag
            return f'machine {m_idx} ({m_name}): fixed ratio between {ref} and {other}'
        if kind == 'balance':
            return f'conservation of "{self.tag[1]}" (production = consumption)'
        if kind == 'pin':
            return f'user pin: {self.tag[1]} = {self.rhs}'
        return str(self.tag)


@dataclass
class VariableInfo:
    name: str
    kind: str                      # 'edge' | 'src' | 'snk'
    edge: tuple                    # (u, v) in the graph this system was built from
    ingredient: str
    machine_idx: Optional[int]     # graph node idx of the machine endpoint (edge vars)


@dataclass
class System:
    """An exact linear system over named nonnegative variables."""
    constraints: list                    # list[Constraint]
    variables: dict                      # name -> VariableInfo
    edge_to_var: dict                    # (u, v) -> name
    graph: nx.MultiDiGraph

    def var_names(self) -> list:
        return list(self.variables.keys())

    def intermediates(self) -> list:
        """Ingredient names that are both produced and consumed by machines
        (the candidate set for binary-gated sources/sinks)."""
        result = []
        G = self.graph
        for idx, node in G.nodes.items():
            nobj = node['object']
            if not isinstance(nobj, IngredientNode):
                continue
            internal_in = any(
                not isinstance(G.nodes[e[0]]['object'], ExternalNode)
                for e in G.in_edges(idx))
            internal_out = any(
                not isinstance(G.nodes[e[1]]['object'], ExternalNode)
                for e in G.out_edges(idx))
            if internal_in and internal_out:
                result.append(nobj.name)
        return result

    def external_vars(self, ingredient: Optional[str] = None) -> list:
        return [v.name for v in self.variables.values()
                if v.kind in ('src', 'snk')
                and (ingredient is None or v.ingredient == ingredient)]


def _edge_ingredient(G, edge) -> str:
    key = edge[2] if len(edge) == 3 else 0
    return G.edges[edge[0], edge[1], key]['object'].name


def build_system(G: nx.MultiDiGraph, pins=(), ratio_form: str = 'star') -> System:
    """Build the exact equality system for a connected graph (externals already
    added by preProcessing.addExternalNodes, or not — both work).

    ratio_form: 'star' gives |I|+|O|-1 ratio rows per machine (no redundancy,
    clean rank/IIS); 'pairwise' reproduces graphToEquations' |I|*|O| rows.
    """
    assert ratio_form in ('star', 'pairwise')
    variables = {}
    edge_to_var = {}
    counters = {'edge': 0, 'src': 0, 'snk': 0}

    def declare(edge, kind, ingredient, machine_idx):
        prefix = {'edge': 'x', 'src': 'src', 'snk': 'snk'}[kind]
        name = f'{prefix}{counters[kind]}'
        counters[kind] += 1
        variables[name] = VariableInfo(name, kind, tuple(edge[:2]), ingredient, machine_idx)
        edge_to_var[tuple(edge[:2])] = name
        return name

    # Declare one variable per (machine|external) <-> ingredient edge.
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, ExternalNode):
            # ExternalNode subclasses MachineNode, so check it first.
            for edge in G.out_edges(idx):
                declare(edge, 'src', _edge_ingredient(G, edge), None)
            for edge in G.in_edges(idx):
                declare(edge, 'snk', _edge_ingredient(G, edge), None)
        elif isinstance(nobj, MachineNode):
            for edge in list(G.in_edges(idx)) + list(G.out_edges(idx)):
                declare(edge, 'edge', _edge_ingredient(G, edge), idx)

    constraints = []

    # Machine ratio constraints. NOTE: unlike graphToEquations (which skips a
    # machine whose input or output side is empty), we couple ALL remaining
    # edges. Water removal can empty a side — e.g. the electrolyzer's only
    # input — and without coupling its outputs, hydrogen and oxygen would
    # become independent free variables (observed: solver emitting hydrogen
    # without the mandatory co-produced oxygen).
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, ExternalNode) or not isinstance(nobj, MachineNode):
            continue
        in_edges = list(G.in_edges(idx))
        out_edges = list(G.out_edges(idx))
        if len(in_edges) + len(out_edges) < 2:
            continue

        def per_craft(edge):
            ing = _edge_ingredient(G, edge)
            qty = nobj.I[ing] if edge[1] == idx else nobj.O[ing]
            return ing, to_frac(qty)

        all_edges = in_edges + out_edges
        if ratio_form == 'star':
            ref = all_edges[0]
            ref_ing, ref_qty = per_craft(ref)
            for edge in all_edges[1:]:
                ing, qty = per_craft(edge)
                # flow(edge)/qty = crafts = flow(ref)/ref_qty
                constraints.append(Constraint(
                    terms=((edge_to_var[tuple(edge[:2])], ref_qty),
                           (edge_to_var[tuple(ref[:2])], -qty)),
                    rhs=Fraction(0),
                    tag=('machine_ratio', idx, nobj.m, ref_ing, ing),
                ))
        else:
            for in_edge in in_edges:
                in_ing, in_qty = per_craft(in_edge)
                for out_edge in out_edges:
                    out_ing, out_qty = per_craft(out_edge)
                    # matches graphToEquations: x_in * (O/I) - x_out == 0
                    constraints.append(Constraint(
                        terms=((edge_to_var[tuple(in_edge[:2])], out_qty / in_qty),
                               (edge_to_var[tuple(out_edge[:2])], Fraction(-1))),
                        rhs=Fraction(0),
                        tag=('machine_ratio', idx, nobj.m, in_ing, out_ing),
                    ))

    # Ingredient balance constraints.
    for idx, node in G.nodes.items():
        nobj = node['object']
        if not isinstance(nobj, IngredientNode):
            continue
        in_edges = list(G.in_edges(idx))
        out_edges = list(G.out_edges(idx))
        if not in_edges or not out_edges:
            continue
        terms = ([(edge_to_var[tuple(e[:2])], Fraction(1)) for e in in_edges]
                 + [(edge_to_var[tuple(e[:2])], Fraction(-1)) for e in out_edges])
        constraints.append(Constraint(
            terms=tuple(terms), rhs=Fraction(0), tag=('balance', nobj.name)))

    # User pins: (edge, value) pairs resolved by corpus.load_case.
    for edge, value in pins:
        constraints.append(Constraint(
            terms=((edge_to_var[tuple(edge[:2])], Fraction(1)),),
            rhs=to_frac(value),
            tag=('pin', edge_to_var[tuple(edge[:2])])))

    return System(constraints=constraints, variables=variables,
                  edge_to_var=edge_to_var, graph=G)
