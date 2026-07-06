"""graphviz dot via pygraphviz — the current-tool baseline. Layered only."""

import pygraphviz as pgv

POINTS_PER_INCH = 72.0


def _parse_pos(pos):
    """dot edge pos syntax: [e,ex,ey] [s,sx,sy] p1 p2 ... pn — the arrow
    ENDpoint is listed FIRST but belongs at the END of the curve, and the
    startpoint (if present) at the beginning. Treating them positionally
    draws every edge from its arrowhead backwards (scribbles with gaps)."""
    end = start = None
    ctrl = []
    for tok in pos.split():
        if tok.startswith('e,'):
            x, y = tok[2:].split(',')[:2]
            end = (float(x), float(y))
        elif tok.startswith('s,'):
            x, y = tok[2:].split(',')[:2]
            start = (float(x), float(y))
        else:
            x, y = tok.split(',')[:2]
            ctrl.append((float(x), float(y)))
    return start, ctrl, end


def _sample_bspline(ctrl, samples_per_seg=8):
    """dot emits cubic B-spline control points (1 + 3n). De Casteljau-sample
    each cubic so crossing/bend metrics see the real curve."""
    if len(ctrl) < 4:
        return ctrl
    out = [ctrl[0]]
    for seg in range((len(ctrl) - 1) // 3):
        p0, p1, p2, p3 = ctrl[3 * seg: 3 * seg + 4]
        for i in range(1, samples_per_seg + 1):
            t = i / samples_per_seg
            mt = 1 - t
            x = (mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0]
                 + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0])
            y = (mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1]
                 + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1])
            out.append((x, y))
    return out


def layout(graph_json: dict, style: str = 'layered') -> dict:
    if style != 'layered':
        raise ValueError('dot only does layered layout')

    ag = pgv.AGraph(directed=True, strict=False,
                    rankdir='TB', splines='spline', ranksep='0.6',
                    nodesep='0.35')
    for node in graph_json['nodes']:
        ag.add_node(node['id'], label=node['label'], shape='box',
                    fixedsize='true',
                    width=node['w'] / POINTS_PER_INCH,
                    height=node['h'] / POINTS_PER_INCH)
    for edge in graph_json['edges']:
        ag.add_edge(edge['src'], edge['dst'], key=edge['id'])
    ag.layout(prog='dot')

    nodes, sizes = {}, {}
    for node in graph_json['nodes']:
        x, y = map(float, ag.get_node(node['id']).attr['pos'].split(','))
        nodes[node['id']] = (x, -y)          # dot's y grows upward; flip
        sizes[node['id']] = (node['w'], node['h'])

    # Index parallel-edge copies once: a per-edge scan of ag.edges() is
    # O(E^2) in pygraphviz object constructions (~11s at 394 machines,
    # dwarfing dot's own 0.7s layout).
    copies_by_pair = {}
    for e in ag.edges(keys=True):
        copies_by_pair.setdefault((e[0], e[1]), []).append(e)

    seen = {}
    edges_out = []
    for edge in graph_json['edges']:
        pair = (edge['src'], edge['dst'])
        copies = copies_by_pair[pair]
        idx = seen.get(pair, 0)
        seen[pair] = idx + 1
        ag_edge = copies[min(idx, len(copies) - 1)]
        start, ctrl, end = _parse_pos(ag.get_edge(*ag_edge).attr['pos'])
        curve = _sample_bspline(ctrl)
        if start is not None:
            curve = [start] + curve
        if end is not None:
            curve = curve + [end]
        pts = [(x, -y) for x, y in curve]
        edges_out.append({'points': pts, 'src': edge['src'],
                          'dst': edge['dst'], 'label': edge['label']})
    return {'nodes': nodes, 'sizes': sizes, 'edges': edges_out,
            'engine': 'dot', 'style': style}
