"""OGDF layout worker — runs in a SUBPROCESS.

Why: cppyy/OGDF failures are C++-level (segfaults, asserts, unbounded
planarization time). In-process, SIGALRM cannot interrupt a running C++
call, so timeouts fire late and crashes take the whole benchmark down,
looking like silent failures. As a subprocess, the parent gets a hard kill
on timeout and a full stderr traceback on error.

stdin:  {"graph": <interchange json>, "style": "layered"|"orthogonal",
         "opts": {"ortho_quality": "good"|"fast",
                  "balancing": float, "layer_distance": float,
                  "node_distance": float}}
stdout: {"nodes": {id: [x, y]}, "edges": [{"id":..., "points": [[x,y]...]}]}
"""

import json
import sys

_saved = sys.modules.get('matplotlib', '__missing__')
sys.modules['matplotlib'] = None    # optional integration crashes cppyy
try:
    from ogdf_python import cppinclude, ogdf
finally:
    if _saved == '__missing__':
        del sys.modules['matplotlib']
    else:
        sys.modules['matplotlib'] = _saved

cppinclude('ogdf/basic/basic.h')
cppinclude('ogdf/layered/SugiyamaLayout.h')
cppinclude('ogdf/layered/OptimalRanking.h')
cppinclude('ogdf/layered/MedianHeuristic.h')
cppinclude('ogdf/layered/OptimalHierarchyLayout.h')
cppinclude('ogdf/planarity/PlanarizationLayout.h')
cppinclude('ogdf/planarity/SubgraphPlanarizer.h')
cppinclude('ogdf/planarity/PlanarSubgraphFast.h')
cppinclude('ogdf/planarity/FixedEmbeddingInserter.h')
cppinclude('ogdf/cluster/ClusterGraph.h')
cppinclude('ogdf/cluster/ClusterGraphAttributes.h')
cppinclude('ogdf/cluster/ClusterPlanarizationLayout.h')


def run_clustered(graph, opts):
    """Cluster-aware orthogonal layout (ClusterPlanarizationLayout): groups
    become OGDF clusters the planarizer must keep contiguous."""
    G, GA, nodes, edges = build(graph)
    CG = ogdf.ClusterGraph(G)
    CGA = ogdf.ClusterGraphAttributes(
        CG, ogdf.GraphAttributes.nodeGraphics | ogdf.GraphAttributes.edgeGraphics
        | ogdf.ClusterGraphAttributes.clusterGraphics)
    for node in graph['nodes']:
        v = nodes[node['id']]
        CGA.width[v] = node['w']
        CGA.height[v] = node['h']
    by_group = {}
    for node in graph['nodes']:
        if node.get('group'):
            by_group.setdefault(node['group'], []).append(nodes[node['id']])
    # Singleton clusters are degenerate for the c-planarizer; skip them.
    by_group = {g: m for g, m in by_group.items() if len(m) >= 2}
    clusters = {}
    for gname, members in sorted(by_group.items()):
        lst = ogdf.SList[ogdf.node]()
        for v in members:
            lst.pushBack(v)
        clusters[gname] = CG.createCluster(lst)

    cpl = ogdf.ClusterPlanarizationLayout()
    try:
        cpl.pageRatio(float(opts.get('page_ratio', 0.5)))  # area/aspect knob
    except Exception:
        pass
    cpl.call(G, CGA, CG)

    out_nodes = {}
    for node in graph['nodes']:
        v = nodes[node['id']]
        out_nodes[node['id']] = [float(CGA.x[v]), float(CGA.y[v])]
    out_edges = []
    for edge in graph['edges']:
        e = edges[edge['id']]
        pts = [out_nodes[edge['src']]]
        for p in CGA.bends[e]:
            pts.append([float(p.m_x), float(p.m_y)])
        pts.append(out_nodes[edge['dst']])
        out_edges.append({'id': edge['id'], 'points': pts})
    groups = {}
    for gname, c in clusters.items():
        groups[gname] = [float(CGA.x(c)), float(CGA.y(c)),
                         float(CGA.width(c)), float(CGA.height(c))]
    return {'nodes': out_nodes, 'edges': out_edges, 'groups': groups}


def _keep(obj):
    obj.__python_owns__ = False     # OGDF takes ownership; avoid double free
    return obj


def build(graph):
    G = ogdf.Graph()
    GA = ogdf.GraphAttributes(
        G, ogdf.GraphAttributes.nodeGraphics | ogdf.GraphAttributes.edgeGraphics)
    nodes = {}
    for node in graph['nodes']:
        v = G.newNode()
        GA.width[v] = node['w']
        GA.height[v] = node['h']
        nodes[node['id']] = v
    edges = {}
    for edge in graph['edges']:
        edges[edge['id']] = G.newEdge(nodes[edge['src']], nodes[edge['dst']])
    return G, GA, nodes, edges


def run(request):
    graph = request['graph']
    style = request['style']
    opts = request.get('opts') or {}
    ogdf.setSeed(int(opts.get('seed', 1337)))   # reproducible layouts
    if style == 'orthogonal' and any(n.get('group') for n in graph['nodes']):
        return run_clustered(graph, opts)
    G, GA, nodes, edges = build(graph)

    if style == 'layered':
        sl = ogdf.SugiyamaLayout()
        sl.setRanking(_keep(ogdf.OptimalRanking()))
        sl.setCrossMin(_keep(ogdf.MedianHeuristic()))
        ohl = ogdf.OptimalHierarchyLayout()
        # 20/8 default: -33% area vs 45/25 with identical crossings and no
        # node overlaps (labels live inside nodes, so tight gaps are fine).
        ohl.layerDistance(float(opts.get('layer_distance', 20.0)))
        ohl.nodeDistance(float(opts.get('node_distance', 8.0)))
        # weightBalancing > 0 spreads nodes to balance segment positions —
        # the main source of the "insane whitespace" complaint.
        ohl.weightBalancing(float(opts.get('balancing', 0.0)))
        sl.setLayout(_keep(ohl))
        sl.call(GA)
    elif style == 'orthogonal':
        pl = ogdf.PlanarizationLayout()
        # 0.5 tames the wide-banner sprawl (palladium_line aspect 2.97 ->
        # 1.88, area -22%) at a small crossing cost; see research.md.
        pl.pageRatio(float(opts.get('page_ratio', 0.5)))
        if opts.get('ortho_quality', 'good') == 'fast':
            # Cheap planar subgraph + fixed-embedding insertion, single
            # permutation: relaxes exactly the exponential-ish part.
            sp = ogdf.SubgraphPlanarizer()
            sp.setSubgraph(_keep(ogdf.PlanarSubgraphFast['int']()))
            sp.setInserter(_keep(ogdf.FixedEmbeddingInserter()))
            sp.permutations(1)
            pl.setCrossMin(_keep(sp))
        pl.call(GA)
    else:
        raise ValueError(style)

    out_nodes = {}
    for node in graph['nodes']:
        v = nodes[node['id']]
        out_nodes[node['id']] = [float(GA.x[v]), float(GA.y[v])]
    out_edges = []
    for edge in graph['edges']:
        e = edges[edge['id']]
        pts = [out_nodes[edge['src']]]
        for p in GA.bends[e]:
            pts.append([float(p.m_x), float(p.m_y)])
        pts.append(out_nodes[edge['dst']])
        out_edges.append({'id': edge['id'], 'points': pts})
    return {'nodes': out_nodes, 'edges': out_edges}


def serve():
    """JSONL loop: one request per line, one response per line. Keeps the
    ~4s cppyy JIT startup to a single payment per benchmark run. Layout
    errors are returned as {'error': ...} so the worker survives them;
    only hard crashes (segfaults) end the process."""
    import traceback
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = run(json.loads(line))
        except Exception:
            response = {'error': traceback.format_exc()}
        sys.stdout.write(json.dumps(response) + '\n')
        sys.stdout.flush()


if __name__ == '__main__':
    if '--serve' in sys.argv:
        serve()
    else:
        request = json.load(sys.stdin)
        json.dump(run(request), sys.stdout)
