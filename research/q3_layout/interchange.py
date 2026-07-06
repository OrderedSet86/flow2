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
    return build_graph_json(case, system, result, lead=lead)


def build_graph_json(case, system, result, lead: str = None,
                     use_yaml_groups: bool = True,
                     auto_subgraphs: bool = False) -> dict:
    """Export a solved case as layout-input JSON (see solved_graph_json).
    Kept separate so a caller (the CLI) can solve once, enumerate/choose an
    alternative gate support, and re-export without re-solving.

    Subgraphs: yaml `group:` names attach to machine nodes; with
    auto_subgraphs=True the experimental sink-claim pass overrides them
    (see sink_claim_groups)."""
    name = case.name
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
        # Every node carries its ingredient names: a machine's identity is
        # its recipe I/O (user rule: "all ingredients need to be taken into
        # account"), used by the stem-affinity subgraph pass.
        if isinstance(nobj, IngredientNode):
            ings = [nobj.name]
        else:
            ings = list(nobj.I) + list(nobj.O)
        node = {'id': str(idx), 'label': lines[0]['t'], 'lines': lines,
                'kind': kind, 'w': w, 'h': h, 'ings': ings}
        if use_yaml_groups and case.groups and idx in case.groups:
            node['group'] = case.groups[idx]
        nodes.append(node)

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
    if auto_subgraphs:
        claims = sink_claim_groups(graph_json)
        for node in graph_json['nodes']:
            if node['id'] in claims:
                node['group'] = claims[node['id']]
            else:
                node.pop('group', None)
    else:
        _adopt_ingredients(graph_json)
    graph_json = canonicalize_order(graph_json)
    if len(graph_json['nodes']) <= ORDER_SEARCH_MAX_NODES:
        graph_json = best_root_order(graph_json, lead=lead)
    return graph_json


# Form/state words carry no subsystem identity. A closed grammar set (GT
# naming convention), not a curated gameplay list — zero-config compliant.
STEM_MODIFIERS = {
    'dust', 'molten', 'ingot', 'solution', 'salt', 'enriched', 'acid',
    'reprecipitated', 'diluted', 'crude', 'acidic', 'residue', 'metallic',
    'powder', 'metal', 'hot', 'refined', 'small', 'tiny', 'pure', 'impure',
    'gas', 'sheet', 'plate', 'block', 'liquid', 'mixture', 'of', 'x',
}


def _stems(names) -> set:
    stems = set()
    for name in names:
        for token in name.lower().replace('-', ' ').split():
            if token not in STEM_MODIFIERS and not token.isdigit():
                stems.add(token)
    return stems


def _adopt_ingredients(graph_json: dict):
    """The interchange format is the internal representation (not v1 yaml):
    ANY node may carry 'group'. v1 yaml only tags machines, so adopt each
    ingredient/external node into a group when every machine neighbor
    belongs to that one group — cross-group traffic then flows box-to-box
    instead of through stray ungrouped nodes."""
    group_of = {n['id']: n.get('group') for n in graph_json['nodes']}
    is_machine = {n['id']: n['kind'] == 'machine' for n in graph_json['nodes']}
    neighbors = {}
    for e in graph_json['edges']:
        neighbors.setdefault(e['src'], set()).add(e['dst'])
        neighbors.setdefault(e['dst'], set()).add(e['src'])
    for node in graph_json['nodes']:
        if node['kind'] == 'machine' or node.get('group'):
            continue
        machine_groups = {group_of[m] for m in neighbors.get(node['id'], ())
                          if is_machine.get(m)}
        if len(machine_groups) == 1 and None not in machine_groups:
            node['group'] = next(iter(machine_groups))


def sink_claim_groups(graph_json: dict) -> dict:
    """Experimental subgraph assignment, working backwards from sinks: every
    node joins the subgraph of its NEAREST sink (BFS hops on reversed
    edges). Ties stay shared (ungrouped). Unique-claim turned out to label
    only each sink's immediate tail — on interwoven charts nearly everything
    reaches several sinks; nearest-sink partitions the whole chart.
    Returns {node_id: group_name}."""
    preds = {}
    degree = {}
    for edge in graph_json['edges']:
        preds.setdefault(edge['dst'], []).append(edge['src'])
        degree[edge['src']] = degree.get(edge['src'], 0) + 1
        degree[edge['dst']] = degree.get(edge['dst'], 0) + 1

    # Commodity hubs (user rule: "nuclear power and vitamin water both need
    # water" is not cohesion): high-degree ingredient nodes connect
    # everything to everything and must not act as connectors — not in the
    # distance BFS, not in adoption votes, not for cluster connectivity.
    # Degree threshold is structural, not a curated ingredient list.
    hubs = {n['id'] for n in graph_json['nodes']
            if n['kind'] == 'ingredient' and degree.get(n['id'], 0) >= 6}

    sinks = [n for n in graph_json['nodes']
             if n['label'].startswith('[Sink]')]
    best = {}          # node_id -> (distance, {groups at that distance})
    for sink in sinks:
        group = sink['label'].removeprefix('[Sink]').strip()
        dist = {sink['id']: 0}
        frontier = [sink['id']]
        while frontier:
            nxt = []
            for nid in frontier:
                if nid in hubs and dist[nid] > 0:
                    continue      # hubs receive a distance but don't relay
                for p in preds.get(nid, ()):
                    if p not in dist:
                        dist[p] = dist[nid] + 1
                        nxt.append(p)
            frontier = nxt
        for nid, d in dist.items():
            if nid not in best or d < best[nid][0]:
                best[nid] = (d, {group})
            elif d == best[nid][0]:
                best[nid][1].add(group)

    assigned = {nid: next(iter(groups))
                for nid, (_, groups) in best.items() if len(groups) == 1}

    # Cohesion rule 1 (user insight: recycling defines subsystems): a whole
    # strongly-connected component shares one group — the most common
    # assignment among its members. Loops stop straddling cluster borders.
    import networkx as nx
    G = nx.DiGraph()
    for e in graph_json['edges']:
        G.add_edge(e['src'], e['dst'])
    # Size cap: real recycle loops are small (the yaml's own "X recycling"
    # groups are 3-6 machines). Interwoven charts have one GIANT core SCC —
    # merging it painted all of 230_platline as a single "chlorine" cluster.
    max_scc = max(8, len(graph_json['nodes']) // 10)
    for scc in nx.strongly_connected_components(G):
        if len(scc) < 2 or len(scc) > max_scc:
            continue
        votes = {}
        for nid in scc:
            if nid in assigned:
                votes[assigned[nid]] = votes.get(assigned[nid], 0) + 1
        if votes:
            winner = max(sorted(votes), key=votes.get)
            for nid in scc:
                assigned[nid] = winner

    # Cohesion rule 2: a still-unassigned node (distance tie) adopts the
    # group when all its assigned neighbors agree.
    neighbors = {}
    for e in graph_json['edges']:
        neighbors.setdefault(e['src'], set()).add(e['dst'])
        neighbors.setdefault(e['dst'], set()).add(e['src'])
    for node in graph_json['nodes']:
        nid = node['id']
        if nid in assigned:
            continue
        around = {assigned[m] for m in neighbors.get(nid, ())
                  if m in assigned and m not in hubs}
        if len(around) == 1:
            assigned[nid] = next(iter(around))

    # Cohesion rule 3 — stem affinity. Form/state modifiers are stripped
    # from ingredient names; the remaining tokens ("palladium", "potassium")
    # are stems. A stem whose carriers sit majority-inside one cluster is
    # OWNED by it; a node whose owned stems all point at one cluster joins
    # it — machines via their full recipe I/O. Two passes let ownership
    # stabilize.
    stems_of = {n['id']: _stems(n.get('ings', ())) for n in graph_json['nodes']}
    for _ in range(2):
        owners = {}
        for nid, group in assigned.items():
            for stem in stems_of.get(nid, ()):
                owners.setdefault(stem, {}).setdefault(group, 0)
                owners[stem][group] += 1
        stem_owner = {}
        for stem, votes in owners.items():
            total = sum(votes.values())
            top_group, top = max(sorted(votes.items()), key=lambda kv: kv[1])
            if top * 2 > total:
                stem_owner[stem] = top_group
        for node in graph_json['nodes']:
            nid = node['id']
            claimed = {stem_owner[s] for s in stems_of.get(nid, ())
                       if s in stem_owner}
            if len(claimed) == 1:
                assigned[nid] = next(iter(claimed))

    # Connectivity guard: stem affinity can pull far-flung same-stem nodes
    # into one group, making it DISCONNECTED — semantically wrong (not a
    # subsystem) and it segfaults OGDF's ClusterPlanarizationLayout. Keep
    # only each group's largest weakly-connected component.
    UG = G.to_undirected()
    by_group = {}
    for nid, group in assigned.items():
        by_group.setdefault(group, set()).add(nid)
    for group, members in by_group.items():
        # Hubs don't hold a cluster together (paths through them removed).
        sub = UG.subgraph(m for m in members if m in UG and m not in hubs)
        comps = sorted(nx.connected_components(sub), key=len, reverse=True)
        for comp in comps[1:]:
            for nid in comp:
                del assigned[nid]
        for nid in members & hubs:
            del assigned[nid]     # commodities belong to the factory

    # Coverage recovery: nodes trimmed by the connectivity guard (or never
    # assigned) join the plurality cluster among their assigned neighbors,
    # iterated to a fixpoint — connected by construction, so the guard
    # stays satisfied. (User target: >=80% coverage.)
    def absorb():
        for _ in range(10):
            changed = False
            for node in graph_json['nodes']:
                nid = node['id']
                if nid in assigned:
                    continue
                votes = {}
                for m in neighbors.get(nid, ()):
                    if m in assigned and m not in hubs:
                        votes[assigned[m]] = votes.get(assigned[m], 0) + 1
                if not votes:
                    continue
                ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
                if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
                    assigned[nid] = ranked[0][0]
                    changed = True
            if not changed:
                break

    absorb()

    # Minimum substance (user rule): a subgraph is only meaningful with at
    # least two machines — dissolve smaller ones and let absorb() re-home
    # their members into adjacent clusters.
    kind_of = {n['id']: n['kind'] for n in graph_json['nodes']}
    machine_count = {}
    for nid, group in assigned.items():
        if kind_of.get(nid) == 'machine':
            machine_count[group] = machine_count.get(group, 0) + 1
    for nid in [n for n, g in assigned.items() if machine_count.get(g, 0) < 2]:
        del assigned[nid]
    absorb()

    # Chain pull (user rule: a producer chain belongs with its consumer):
    # a node whose non-hub consumers sit entirely in ONE cluster follows
    # them, provided its own upstream is unassigned or already there and it
    # has no real tie to a different cluster. Pulls linear supply tails
    # (source -> ingredient -> machine -> product) inside the cluster that
    # eats their output, instead of leaving them dangling outside.
    succs = {}
    for e in graph_json['edges']:
        succs.setdefault(e['src'], []).append(e['dst'])
    for _ in range(10):
        changed = False
        for node in graph_json['nodes']:
            nid = node['id']
            down = {assigned[s] for s in succs.get(nid, ())
                    if s in assigned and s not in hubs}
            if len(down) != 1:
                continue
            target = next(iter(down))
            if assigned.get(nid) == target:
                continue
            up_ok = all(assigned.get(p, target) == target
                        for p in preds.get(nid, ()) if p not in hubs)
            lateral = {assigned[m] for m in neighbors.get(nid, ())
                       if m in assigned and m not in hubs}
            if up_ok and lateral <= {target}:
                assigned[nid] = target
                changed = True
        if not changed:
            break

    # Cohesion rule 4: a degree-1 external ([Source]/[Sink] pseudo node)
    # always follows its sole neighbor — splitting "[Source] PMP" from
    # "PMP" is never meaningful.
    for node in graph_json['nodes']:
        nid = node['id']
        near = neighbors.get(nid, set())
        if node['kind'] == 'external' and len(near) == 1:
            other = next(iter(near))
            if other in assigned:
                assigned[nid] = assigned[other]
            else:
                assigned.pop(nid, None)
    return assigned


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
