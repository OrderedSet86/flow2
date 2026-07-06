"""Engine-agnostic layout quality metrics, computed from the common layout
output format:
    {'nodes': {id: (x, y)},          # centers
     'edges': [{'points': [(x, y), ...], 'src': id, 'dst': id}],
     'sizes': {id: (w, h)}}
"""

import math


def _orient(p, q, r):
    v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return 0 if abs(v) < 1e-9 else (1 if v > 0 else -1)


def _segments_cross(a1, a2, b1, b2):
    """Proper crossing only (shared endpoints don't count)."""
    if max(min(a1[0], a2[0]), min(b1[0], b2[0])) > \
       min(max(a1[0], a2[0]), max(b1[0], b2[0])) + 1e-9:
        return False
    if max(min(a1[1], a2[1]), min(b1[1], b2[1])) > \
       min(max(a1[1], a2[1]), max(b1[1], b2[1])) + 1e-9:
        return False
    o1, o2 = _orient(a1, a2, b1), _orient(a1, a2, b2)
    o3, o4 = _orient(b1, b2, a1), _orient(b1, b2, a2)
    return o1 != o2 and o3 != o4 and 0 not in (o1, o2, o3, o4)


def _edge_bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def crossings(layout) -> int:
    edges = layout['edges']
    # Whole-edge bbox prefilter: without it, spline-sampled edges (16+
    # segments each) cost ~256 segment tests per pair — minutes at 2000
    # edges. Most pairs are nowhere near each other.
    boxes = [_edge_bbox(e['points']) for e in edges]
    total = 0
    for i in range(len(edges)):
        bi = boxes[i]
        for j in range(i + 1, len(edges)):
            bj = boxes[j]
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            e, f = edges[i], edges[j]
            if {e['src'], e['dst']} & {f['src'], f['dst']}:
                continue      # shared node: touching there is not a crossing
            pts_e, pts_f = e['points'], f['points']
            hit = False
            for a in range(len(pts_e) - 1):
                for b in range(len(pts_f) - 1):
                    if _segments_cross(pts_e[a], pts_e[a + 1],
                                       pts_f[b], pts_f[b + 1]):
                        hit = True
                        break
                if hit:
                    break
            total += hit      # count crossing PAIRS, not segment hits
    return total


def bends(layout, angle_thresh_deg=15) -> int:
    total = 0
    for edge in layout['edges']:
        pts = edge['points']
        for i in range(1, len(pts) - 1):
            v1 = (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
            v2 = (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            n1, n2 = math.hypot(*v1), math.hypot(*v2)
            if n1 < 1e-9 or n2 < 1e-9:
                continue
            cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
            if math.degrees(math.acos(cos)) > angle_thresh_deg:
                total += 1
    return total


def edge_length(layout) -> float:
    total = 0.0
    for edge in layout['edges']:
        pts = edge['points']
        for i in range(len(pts) - 1):
            total += math.hypot(pts[i + 1][0] - pts[i][0],
                                pts[i + 1][1] - pts[i][1])
    return total


def bbox(layout):
    xs, ys = [], []
    for nid, (x, y) in layout['nodes'].items():
        w, h = layout['sizes'].get(nid, (0, 0))
        xs += [x - w / 2, x + w / 2]
        ys += [y - h / 2, y + h / 2]
    for edge in layout['edges']:
        for x, y in edge['points']:
            xs.append(x)
            ys.append(y)
    if not xs:
        return 0.0, 0.0
    return max(xs) - min(xs), max(ys) - min(ys)


def node_overlaps(layout) -> int:
    ids = list(layout['nodes'])
    count = 0
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            ax, ay = layout['nodes'][a]
            bx, by = layout['nodes'][b]
            aw, ah = layout['sizes'].get(a, (0, 0))
            bw, bh = layout['sizes'].get(b, (0, 0))
            if abs(ax - bx) < (aw + bw) / 2 - 1e-6 and \
               abs(ay - by) < (ah + bh) / 2 - 1e-6:
                count += 1
    return count


def _crossing_points(layout):
    pts = []
    edges = layout['edges']
    boxes = [_edge_bbox(e['points']) for e in edges]
    for i in range(len(edges)):
        bi = boxes[i]
        for j in range(i + 1, len(edges)):
            bj = boxes[j]
            if bi[2] < bj[0] or bj[2] < bi[0] or bi[3] < bj[1] or bj[3] < bi[1]:
                continue
            e, f = edges[i], edges[j]
            if {e['src'], e['dst']} & {f['src'], f['dst']}:
                continue
            for a in range(len(e['points']) - 1):
                for b in range(len(f['points']) - 1):
                    a1, a2 = e['points'][a], e['points'][a + 1]
                    b1, b2 = f['points'][b], f['points'][b + 1]
                    if _segments_cross(a1, a2, b1, b2):
                        d = ((a2[0] - a1[0]) * (b2[1] - b1[1])
                             - (a2[1] - a1[1]) * (b2[0] - b1[0]))
                        if abs(d) > 1e-9:
                            t = ((b1[0] - a1[0]) * (b2[1] - b1[1])
                                 - (b1[1] - a1[1]) * (b2[0] - b1[0])) / d
                            pts.append((a1[0] + t * (a2[0] - a1[0]),
                                        a1[1] + t * (a2[1] - a1[1])))
    return pts


def crossing_clusters(layout, radius=18.0) -> int:
    """User readability condition B: "confusing intersections" — crossing
    points packed within `radius` of another crossing. Returns how many
    crossings sit in a cluster (0 = every intersection is isolated)."""
    pts = _crossing_points(layout)
    clustered = 0
    for i, p in enumerate(pts):
        for j, q in enumerate(pts):
            if i != j and math.hypot(p[0] - q[0], p[1] - q[1]) < radius:
                clustered += 1
                break
    return clustered


def parallel_bundles(layout, dist=12.0, min_len=60.0) -> int:
    """User readability condition A: closely packed parallel runs — pairs of
    near-parallel long segments from DIFFERENT edges closer than `dist`.
    Mentally following 1 of 30 stacked lines is hard; lower is better."""
    segs = []
    for ei, edge in enumerate(layout['edges']):
        pts = edge['points']
        for i in range(len(pts) - 1):
            length = math.hypot(pts[i + 1][0] - pts[i][0],
                                pts[i + 1][1] - pts[i][1])
            if length >= min_len:
                segs.append((ei, pts[i], pts[i + 1], length))
    count = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            e1, a1, a2, l1 = segs[i]
            e2, b1, b2, l2 = segs[j]
            if e1 == e2:
                continue
            v1 = ((a2[0] - a1[0]) / l1, (a2[1] - a1[1]) / l1)
            v2 = ((b2[0] - b1[0]) / l2, (b2[1] - b1[1]) / l2)
            if abs(v1[0] * v2[0] + v1[1] * v2[1]) < 0.98:
                continue      # not parallel
            # midpoint distance as a cheap separation proxy
            m1 = ((a1[0] + a2[0]) / 2, (a1[1] + a2[1]) / 2)
            m2 = ((b1[0] + b2[0]) / 2, (b1[1] + b2[1]) / 2)
            if math.hypot(m1[0] - m2[0], m1[1] - m2[1]) < dist:
                count += 1
    return count


# The readability metrics are O(segments^2); above this many edges they take
# minutes and mean little (nobody traces edges on a 2000-edge chart).
READABILITY_MAX_EDGES = 600


def all_metrics(layout) -> dict:
    w, h = bbox(layout)
    small = len(layout['edges']) <= READABILITY_MAX_EDGES
    return {
        'crossings': crossings(layout),
        'bends': bends(layout),
        'edge_length': round(edge_length(layout), 1),
        'area': round(w * h / 1e4, 1),          # in 100px^2 units
        'aspect': round(w / h, 2) if h else 0.0,
        'node_overlaps': node_overlaps(layout),
        'crossing_clusters': crossing_clusters(layout) if small else '',
        'parallel_bundles': parallel_bundles(layout) if small else '',
    }
