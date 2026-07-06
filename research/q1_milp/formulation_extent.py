"""Variant B — recipe-extent formulation (Kirk McDonald / factoriolab style).

One variable t_m >= 0 per machine ("crafts per second"); every edge flow is
a DERIVED quantity (per-craft qty * t_m). Machine-ratio rows vanish; one
balance row per ingredient remains. For palladium_line this shrinks ~341
variables / ~207 rows (edge form) to ~124 variables / ~63 rows.

The System produced here is driver-compatible: solve_lexicographic treats
t_m as the machine's reference "edge", so stages, gates, floors, and
validation all work unchanged.
"""

from fractions import Fraction

import networkx as nx

from research.common.provenance import (Constraint, System, VariableInfo,
                                        to_frac)
from src.data.basicTypes import ExternalNode, IngredientNode, MachineNode


def build_extent_system(G: nx.MultiDiGraph, pins=()) -> System:
    variables = {}
    edge_to_var = {}
    counters = {'src': 0, 'snk': 0}

    machine_t = {}
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, ExternalNode) or not isinstance(nobj, MachineNode):
            continue
        name = f't{idx}'
        machine_t[idx] = name
        # Register t_m as an 'edge' variable whose per-craft quantity is 1:
        # lexicographic's _per_craft resolves nobj.I/O[ingredient], so point
        # the info at a real ingredient and divide pins accordingly instead.
        # Point it at the machine's first ingredient; the synthetic edge's
        # direction tells _per_craft whether to look in I or O.
        first_ing = next(iter(list(nobj.I) + list(nobj.O)), '')
        edge = (-1, idx) if first_ing in nobj.I else (idx, -1)
        variables[name] = VariableInfo(name, 'edge', edge, first_ing, idx)

    def _external_var(edge, kind, ingredient):
        name = f'{kind}{counters[kind]}'
        counters[kind] += 1
        variables[name] = VariableInfo(name, kind, tuple(edge[:2]), ingredient, None)
        edge_to_var[tuple(edge[:2])] = name
        return name

    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, ExternalNode):
            for edge in G.out_edges(idx):
                key = edge[2] if len(edge) == 3 else 0
                ing = G.edges[edge[0], edge[1], key]['object'].name
                _external_var(edge, 'src', ing)
            for edge in G.in_edges(idx):
                key = edge[2] if len(edge) == 3 else 0
                ing = G.edges[edge[0], edge[1], key]['object'].name
                _external_var(edge, 'snk', ing)

    constraints = []
    for idx, node in G.nodes.items():
        nobj = node['object']
        if not isinstance(nobj, IngredientNode):
            continue
        ing = nobj.name
        terms = {}
        for m_idx, t_name in machine_t.items():
            mobj = G.nodes[m_idx]['object']
            coeff = to_frac(mobj.O.get(ing, 0)) - to_frac(mobj.I.get(ing, 0))
            if coeff:
                terms[t_name] = terms.get(t_name, Fraction(0)) + coeff
        for edge in G.in_edges(idx):
            if isinstance(G.nodes[edge[0]]['object'], ExternalNode):
                terms[edge_to_var[tuple(edge[:2])]] = Fraction(1)
        for edge in G.out_edges(idx):
            if isinstance(G.nodes[edge[1]]['object'], ExternalNode):
                terms[edge_to_var[tuple(edge[:2])]] = Fraction(-1)
        if not terms:
            continue
        constraints.append(Constraint(terms=tuple(terms.items()),
                                      rhs=Fraction(0), tag=('balance', ing)))

    # Pins arrive as ((u, v), value) EDGE pins from corpus; translate to the
    # machine endpoint's extent: flow = per_craft * t  =>  t = value/per_craft.
    for (u, v), value in pins:
        if u in machine_t or v in machine_t:
            m_idx = u if u in machine_t else v
            mobj = G.nodes[m_idx]['object']
            other = v if m_idx == u else u
            ing = G.nodes[other]['object'].name
            per_craft = to_frac(mobj.I[ing] if v == m_idx else mobj.O[ing])
            constraints.append(Constraint(
                terms=((machine_t[m_idx], per_craft),),
                rhs=to_frac(value), tag=('pin', machine_t[m_idx])))
        else:
            raise ValueError(f'pin edge {(u, v)} touches no machine')

    return System(constraints=constraints, variables=variables,
                  edge_to_var=edge_to_var, graph=G)


def derived_edge_flows(system: System, values: dict) -> dict:
    """(u, v) -> flow for every machine<->ingredient edge, from extents."""
    G = system.graph
    flows = {}
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, ExternalNode) or not isinstance(nobj, MachineNode):
            continue
        t = values.get(f't{idx}', 0.0)
        for edge in G.in_edges(idx):
            key = edge[2] if len(edge) == 3 else 0
            ing = G.edges[edge[0], edge[1], key]['object'].name
            flows[tuple(edge[:2])] = float(nobj.I[ing]) * t
        for edge in G.out_edges(idx):
            key = edge[2] if len(edge) == 3 else 0
            ing = G.edges[edge[0], edge[1], key]['object'].name
            flows[tuple(edge[:2])] = float(nobj.O[ing]) * t
    for info in system.variables.values():
        if info.kind in ('src', 'snk'):
            flows[info.edge] = values.get(info.name, 0.0)
    return flows
