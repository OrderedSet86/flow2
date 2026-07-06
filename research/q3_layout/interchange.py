"""Canonical layout-input JSON: every engine sees identical nodes (with
pre-computed sizes), edges, and labels, so metric differences are purely the
layout algorithm's doing.

Machine nodes carry the full recipe (per-craft I/O, machine count, cycle,
EU/t) so a chart can be read without opening NEI — matching gtnh-flow v1's
node style at the user's request.
"""

from research.common.corpus import load_case
from research.common.provenance import build_system
from research.q1_milp.lexicographic import ZERO, solve_lexicographic
from src.data.basicTypes import ExternalNode, IngredientNode, MachineNode

CHAR_W = 6.6      # crude but engine-neutral text metrics (11px sans)
PAD_W, LINE_H, PAD_H = 16.0, 13.0, 10.0


def _fmt_qty(q):
    if q == int(q):
        q = int(q)
    return f'{q:g}'


def _machine_lines(nobj, crafts_per_s):
    """v1-style recipe block: inputs, machine summary, outputs. Each
    ingredient line also carries its SOLVED per-second rate, so the node is
    self-sufficient — on large graphs edge labels are unreadable (user
    feedback), so the node must tell the whole story."""
    count = crafts_per_s * float(nobj.dur)

    def rate(q):
        return f' ({q * crafts_per_s:.4g}/s)'

    lines = [{'t': f'{_fmt_qty(q)}x {ing}{rate(q)}', 'k': 'in'}
             for ing, q in nobj.I.items()]
    lines.append({'t': f'{count:.3g}x {nobj.m}', 'k': 'name'})
    lines.append({'t': f'Cycle: {_fmt_qty(nobj.dur)}s   EU/t: {_fmt_qty(nobj.eut)}',
                  'k': 'meta'})
    lines += [{'t': f'{_fmt_qty(q)}x {ing}{rate(q)}', 'k': 'out'}
              for ing, q in nobj.O.items()]
    return lines


def _node_size(lines):
    width = max(len(line['t']) for line in lines) * CHAR_W + PAD_W
    return (max(width, 60.0), len(lines) * LINE_H + PAD_H)


def solved_graph_json(name: str, backend: str = 'highs',
                      lead: str = None) -> dict:
    """Solve a corpus case zero-config and export the pruned solved graph.

    lead: optional substring naming the chart's primary input (e.g. 'PMP').
    Which source is "the" canonical entry is semantic knowledge the graph
    does not contain — in PlanNH terms this is a one-click "mark as primary
    input" hint. When set, the layout order leads with that root (accepting
    its crossing count); when unset, the crossings-optimal root wins.
    """
    case = load_case(name)
    system = build_system(case.graph, [(p.edge, p.value) for p in case.pins])
    result = solve_lexicographic(system, backend=backend)
    assert result.status == 'optimal', f'{name}: {result.status}'

    G = case.graph
    keep_edges = []
    for info in system.variables.values():
        flow = result.values.get(info.name, 0.0)
        if flow > ZERO:
            keep_edges.append((info.edge, info.ingredient, flow))

    used_nodes = {u for (u, v), _, _ in keep_edges} | \
                 {v for (u, v), _, _ in keep_edges}

    # crafts/s per machine from any solved edge (ratios make them agree)
    crafts = {}
    for info in system.variables.values():
        if info.kind != 'edge' or info.machine_idx is None:
            continue
        flow = result.values.get(info.name, 0.0)
        nobj = G.nodes[info.machine_idx]['object']
        per_craft = (nobj.I.get(info.ingredient) if info.edge[1] == info.machine_idx
                     else nobj.O.get(info.ingredient))
        if per_craft:
            crafts.setdefault(info.machine_idx, flow / float(per_craft))

    nodes = []
    for idx in sorted(used_nodes):
        nobj = G.nodes[idx]['object']
        if isinstance(nobj, ExternalNode):
            kind, lines = 'external', [{'t': nobj.m, 'k': 'name'}]
        elif isinstance(nobj, MachineNode):
            # v1-style yamls contain literal "[Source] X"/"[Sink] X" pseudo-
            # machines; style them as externals (cf. pulp_solver.py:203).
            if nobj.m.startswith(('[Source]', '[Sink]')):
                kind, lines = 'external', [{'t': nobj.m, 'k': 'name'}]
            else:
                kind = 'machine'
                lines = _machine_lines(nobj, crafts.get(idx, 0.0))
        elif isinstance(nobj, IngredientNode):
            throughput = sum(flow for (u, v), _, flow in keep_edges if v == idx)
            kind = 'ingredient'
            lines = [{'t': nobj.name, 'k': 'name'},
                     {'t': f'{throughput:.4g}/s', 'k': 'meta'}]
        else:
            continue
        w, h = _node_size(lines)
        nodes.append({'id': str(idx), 'label': lines[0]['t'], 'lines': lines,
                      'kind': kind, 'w': w, 'h': h})

    edges = []
    for i, ((u, v), ingredient, flow) in enumerate(sorted(keep_edges)):
        edges.append({'id': f'e{i}', 'src': str(u), 'dst': str(v),
                      'label': f'{flow:.4g}/s', 'ingredient': ingredient})

    for edge in edges:
        edge['back'] = False
    for i in _back_edge_indices(edges):
        edges[i]['back'] = True

    graph_json = {'name': name, 'nodes': nodes, 'edges': edges,
                  'meta': {'machines_used': result.machines_used,
                           'gates': result.source_count}}
    graph_json = canonicalize_order(graph_json)
    if len(graph_json['nodes']) <= ORDER_SEARCH_MAX_NODES:
        graph_json = best_root_order(graph_json, lead=lead)
    return graph_json


def canonicalize_order(graph_json: dict) -> dict:
    """Deterministic, structure-derived model order.

    Layered engines are model-order sensitive: DFS cycle breaking enters the
    graph in node order, and on loop-dense charts (platline) a shuffled
    order moved [Source] PMP from the top to 75% down and swung crossings
    6 -> 29. NEI insertion order is arbitrary, so we recompute the order
    from invariants: nodes sorted by descending longest-path height in the
    SCC condensation (the source feeding the deepest chain leads), ties
    broken by label. Same input chart => same order => same layout,
    regardless of how the user added recipes.
    """
    import networkx as nx

    G = nx.DiGraph()
    for node in graph_json['nodes']:
        G.add_node(node['id'])
    for edge in graph_json['edges']:
        G.add_edge(edge['src'], edge['dst'])

    cond = nx.condensation(G)
    height = {}
    for scc in reversed(list(nx.topological_sort(cond))):
        succ = [height[s] for s in cond.successors(scc)]
        height[scc] = 1 + max(succ, default=0) + len(cond.nodes[scc]['members'])
    node_height = {}
    for scc, data in cond.nodes(data=True):
        for member in data['members']:
            node_height[member] = height[scc]

    graph_json['nodes'].sort(
        key=lambda n: (-node_height[n['id']], n['label'], n['id']))
    _sort_edges(graph_json)
    return graph_json


def _sort_edges(graph_json):
    order = {n['id']: i for i, n in enumerate(graph_json['nodes'])}
    graph_json['edges'].sort(
        key=lambda e: (order[e['src']], order[e['dst']], e['ingredient']))


ORDER_SEARCH_MAX_NODES = 300
ORDER_SEARCH_ROOTS = 16


def best_root_order(graph_json: dict, lead: str = None) -> dict:
    """Deterministic order SEARCH: the canonical order is stable but not
    necessarily good (on 230_platline it scored 14 crossings where a
    PMP-led order scores 6, and the semantically-primary input sat
    mid-chart). Generate one candidate order per top source root (BFS from
    that root first), score each with a real ELK layout, keep the best —
    every step is deterministic, so arbitrary NEI insertion order still
    cannot change the result."""
    import json as _json

    from research.q3_layout.engines.elk_engine import layout as elk_layout
    from research.q3_layout.metrics import crossings

    in_deg = {n['id']: 0 for n in graph_json['nodes']}
    succ = {n['id']: [] for n in graph_json['nodes']}
    for e in graph_json['edges']:
        in_deg[e['dst']] += 1
        succ[e['src']].append(e['dst'])
    node_pos = {n['id']: i for i, n in enumerate(graph_json['nodes'])}
    roots = [nid for nid, d in sorted(in_deg.items(),
                                      key=lambda kv: node_pos[kv[0]])
             if d == 0][:ORDER_SEARCH_ROOTS]
    if lead:
        label_of = {n['id']: n['label'] for n in graph_json['nodes']}
        led = [r for r in roots if lead.lower() in label_of[r].lower()]
        if led:
            roots = led

    def root_led(root):
        gj = _json.loads(_json.dumps(graph_json))
        seen, order = {root}, [root]
        frontier = [root]
        while frontier:
            nxt = []
            for nid in frontier:
                for s in sorted(succ[nid], key=node_pos.get):
                    if s not in seen:
                        seen.add(s)
                        order.append(s)
                        nxt.append(s)
            frontier = nxt
        rank = {nid: i for i, nid in enumerate(order)}
        gj['nodes'].sort(key=lambda n: (rank.get(n['id'], 10 ** 9),
                                        node_pos[n['id']]))
        _sort_edges(gj)
        return gj

    candidates = [root_led(r) for r in roots]
    if not lead:
        candidates = [graph_json] + candidates
    scored = []
    for i, cand in enumerate(candidates):
        try:
            score = crossings(elk_layout(cand, 'orthogonal'))
        except Exception:
            continue
        scored.append((score, i, cand))
    if not scored:
        return graph_json
    scored.sort(key=lambda t: (t[0], t[1]))
    return scored[0][2]


def _back_edge_indices(edges):
    """Indices of DFS back edges — the edges that close recycling loops.
    Graph-theoretic (not geometric), so the same edges are dashed in every
    engine's rendering. DFS starts from source-like nodes (in-degree 0)
    for a stable, flow-respecting classification."""
    out = {}
    indegree = {}
    for i, edge in enumerate(edges):
        out.setdefault(edge['src'], []).append((edge['dst'], i))
        indegree[edge['dst']] = indegree.get(edge['dst'], 0) + 1
        indegree.setdefault(edge['src'], indegree.get(edge['src'], 0))

    color = {}                    # 0/absent = white, 1 = on stack, 2 = done
    back = []

    def dfs(root):
        stack = [(root, iter(out.get(root, ())))]
        color[root] = 1
        while stack:
            node, it = stack[-1]
            for nxt, edge_i in it:
                state = color.get(nxt, 0)
                if state == 1:
                    back.append(edge_i)      # closes a cycle
                elif state == 0:
                    color[nxt] = 1
                    stack.append((nxt, iter(out.get(nxt, ()))))
                    break
            else:
                color[node] = 2
                stack.pop()

    roots = sorted((n for n, d in indegree.items() if d == 0), key=str)
    for root in roots:
        if color.get(root, 0) == 0:
            dfs(root)
    for node in sorted(indegree, key=str):   # leftovers: pure cycles
        if color.get(node, 0) == 0:
            dfs(node)
    return back
