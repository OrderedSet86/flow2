"""grandalf — pure-Python Sugiyama; the 'no native deps at all' data point."""

from grandalf.graphs import Edge, Graph, Vertex
from grandalf.layouts import SugiyamaLayout


class _View:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.xy = (0, 0)


def layout(graph_json: dict, style: str = 'layered') -> dict:
    if style != 'layered':
        raise ValueError('grandalf only does layered layout')

    vertices = {}
    for node in graph_json['nodes']:
        v = Vertex(node['id'])
        v.view = _View(node['w'], node['h'])
        vertices[node['id']] = v
    edges = [Edge(vertices[e['src']], vertices[e['dst']])
             for e in graph_json['edges']]
    g = Graph(list(vertices.values()), edges)

    nodes, sizes = {}, {}
    for core in g.C:      # one Sugiyama pass per connected component
        sug = SugiyamaLayout(core)
        sug.init_all()
        sug.draw(3)

    x_off = 0.0
    for core in g.C:
        min_x = min(v.view.xy[0] - v.view.w / 2 for v in core.sV)
        max_x = max(v.view.xy[0] + v.view.w / 2 for v in core.sV)
        for v in core.sV:
            nodes[v.data] = (v.view.xy[0] - min_x + x_off, v.view.xy[1])
            sizes[v.data] = (v.view.w, v.view.h)
        x_off += (max_x - min_x) + 60.0

    edges_out = []
    for edge in graph_json['edges']:
        edges_out.append({'points': [nodes[edge['src']], nodes[edge['dst']]],
                          'src': edge['src'], 'dst': edge['dst'],
                          'label': edge['label']})
    from research.q3_layout.engines.clip import clip_layout
    # grandalf endpoints are node centers; clip so arrowheads are visible.
    return clip_layout({'nodes': nodes, 'sizes': sizes, 'edges': edges_out,
                        'engine': 'grandalf', 'style': style})
