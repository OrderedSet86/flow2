"""Clip polylines to node rectangle boundaries.

dot and ELK emit edge endpoints on the node border; OGDF and grandalf emit
node CENTERS, which buries the arrowhead under the node box when rendered.
"""


def _inside(pt, center, size):
    return (abs(pt[0] - center[0]) <= size[0] / 2 + 1e-9 and
            abs(pt[1] - center[1]) <= size[1] / 2 + 1e-9)


def _boundary_hit(inside_pt, outside_pt, center, size):
    """Intersection of the segment with the rect border, walking from the
    outside point toward the inside one."""
    hw, hh = size[0] / 2, size[1] / 2
    dx = inside_pt[0] - outside_pt[0]
    dy = inside_pt[1] - outside_pt[1]
    best_t = 1.0
    for coord, delta, half, c in ((0, dx, hw, center[0]), (1, dy, hh, center[1])):
        if abs(delta) < 1e-12:
            continue
        for side in (c - half, c + half):
            t = (side - outside_pt[coord]) / delta
            if 0.0 <= t < best_t:
                other = 1 - coord
                v = outside_pt[other] + (dy if other else dx) * t
                lim = (center[other] - (hh if other else hw),
                       center[other] + (hh if other else hw))
                if lim[0] - 1e-9 <= v <= lim[1] + 1e-9:
                    best_t = t
    return (outside_pt[0] + dx * best_t, outside_pt[1] + dy * best_t)


def _clip_end(points, center, size):
    """Truncate the tail of `points` at the rect border around `center`."""
    while len(points) >= 2 and _inside(points[-2], center, size):
        points.pop()
    if len(points) >= 2 and _inside(points[-1], center, size):
        points[-1] = _boundary_hit(points[-1], points[-2], center, size)
    return points


def clip_polyline(points, src_center, src_size, dst_center, dst_size):
    pts = [tuple(p) for p in points]
    if len(pts) < 2:
        return pts
    pts = _clip_end(pts, dst_center, dst_size)
    pts.reverse()
    pts = _clip_end(pts, src_center, src_size)
    pts.reverse()
    return pts


def _dedupe(points, min_seg=3.0):
    """Drop near-zero segments. Clipping can leave a tiny stub as the final
    segment, and the SVG arrow marker orients along it — producing arrows
    that point sideways/backwards ("smushed")."""
    if len(points) < 3:
        return points
    out = [points[0]]
    for pt in points[1:-1]:
        if abs(pt[0] - out[-1][0]) + abs(pt[1] - out[-1][1]) >= min_seg:
            out.append(pt)
    last = points[-1]
    while len(out) > 1 and \
            abs(last[0] - out[-1][0]) + abs(last[1] - out[-1][1]) < min_seg:
        out.pop()
    out.append(last)
    return out


def clip_layout(layout) -> dict:
    """Apply boundary clipping to every edge of a layout in-place."""
    nodes, sizes = layout['nodes'], layout['sizes']
    for edge in layout['edges']:
        edge['points'] = _dedupe(clip_polyline(
            edge['points'],
            nodes[edge['src']], sizes[edge['src']],
            nodes[edge['dst']], sizes[edge['dst']]))
    return layout
