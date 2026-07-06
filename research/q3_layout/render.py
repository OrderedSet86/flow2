"""One shared SVG renderer for all engines: visual style is identical, so
side-by-side differences are purely node positions and edge routes."""

THEMES = {
    'light': {
        'bg': 'white', 'title': '#555',
        'fill': {'machine': '#d5f0d5', 'ingredient': '#f6d9d9',
                 'external': '#e6d9f2'},
        'stroke': {'machine': '#3a7d3a', 'ingredient': '#a33f3f',
                   'external': '#6d3fa3'},
        'line': {'in': '#8a2f2f', 'out': '#2f6a2f', 'name': '#111',
                 'meta': '#555'},
        'edge_opacity': '0.75',
        'palette': ['#c0392b', '#2471a3', '#1e8449', '#af601a', '#7d3c98',
                    '#117a8b', '#b7950b', '#6c3483', '#148f77', '#a04000',
                    '#5d6d7e', '#884ea0'],
        'tint_base': (255, 255, 255),
    },
    'dark': {   # v1 gtnh-flow reads dark; user preference
        'bg': '#16222e', 'title': '#8fa3b5',
        'fill': {'machine': '#1e3527', 'ingredient': '#3b2426',
                 'external': '#2b2340'},
        'stroke': {'machine': '#5dbb7f', 'ingredient': '#d97b7b',
                   'external': '#a98fe0'},
        'line': {'in': '#e89a9a', 'out': '#8fd6a0', 'name': '#f2f5f7',
                 'meta': '#93a4b3'},
        'edge_opacity': '0.9',
        'palette': ['#e8705f', '#5da9e8', '#5fce85', '#e8a25f', '#c08ae8',
                    '#54c8dd', '#e8d05f', '#b07fd6', '#59d6b6', '#e8835f',
                    '#9fb4c8', '#d67fd0'],
        'tint_base': (22, 34, 46),
    },
}
MARGIN = 40.0



def _edge_color(ingredient, theme='dark'):
    import zlib
    pal = THEMES[theme]['palette']
    return pal[zlib.crc32(ingredient.encode()) % len(pal)]


def _tint(hex_color, theme='dark', keep=0.09):
    """Blend a color toward the theme background (solid tint)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    base = THEMES[theme]['tint_base']
    mix = lambda c, b0: int(b0 + (c - b0) * keep)
    return f'#{mix(r, base[0]):02x}{mix(g, base[1]):02x}{mix(b, base[2]):02x}'


def to_svg(layout, graph_json, title='', theme='dark') -> str:
    T = THEMES[theme]
    xs, ys = [], []
    for nid, (x, y) in layout['nodes'].items():
        w, h = layout['sizes'][nid]
        xs += [x - w / 2, x + w / 2]
        ys += [y - h / 2, y + h / 2]
    for edge in layout['edges']:
        for x, y in edge['points']:
            xs.append(x)
            ys.append(y)
    min_x, min_y = min(xs) - MARGIN, min(ys) - MARGIN
    width = max(xs) - min(xs) + 2 * MARGIN
    height = max(ys) - min(ys) + 2 * MARGIN + 24

    def tx(x):
        return x - min_x

    def ty(y):
        return y - min_y + 24

    kind_of = {n['id']: n['kind'] for n in graph_json['nodes']}
    lines_of = {n['id']: n.get('lines', [{'t': n['label'], 'k': 'name'}])
                for n in graph_json['nodes']}
    LINE_FILL = T['line']

    # Subgraph boxes (drawn first, as background). Visual language kept
    # distinct from edges: solid muted hairline + pale solid tint (dashes
    # mean recycling edges; saturated colors mean edge routes; opacity is
    # avoided because ImageMagick ignores it). Engine-provided rects (ELK
    # compound nodes) take precedence; otherwise member bounding boxes.
    group_parts = []
    group_labels = []
    member_map = {}
    for node in graph_json['nodes']:
        if node.get('group') and node['id'] in layout['nodes']:
            member_map.setdefault(node['group'], []).append(node['id'])
    engine_rects = layout.get('groups') or {}
    for gname in sorted(member_map):
        members = member_map[gname]
        # A group with no machine in it (just a sink and its ingredient)
        # conveys nothing — skip the box.
        if not any(kind_of.get(nid) == 'machine' for nid in members):
            continue
        if gname in engine_rects:
            rx, ry, rw, rh = engine_rects[gname]
            gx, gy = tx(rx), ty(ry)
            gw, gh = rw, rh
        else:
            gxs, gys = [], []
            for nid in members:
                x, y = layout['nodes'][nid]
                w, h = layout['sizes'][nid]
                gxs += [x - w / 2, x + w / 2]
                gys += [y - h / 2, y + h / 2]
            pad = 10
            gx, gy = tx(min(gxs)) - pad, ty(min(gys)) - pad
            gw = max(gxs) - min(gxs) + 2 * pad
            gh = max(gys) - min(gys) + 2 * pad
        color = _edge_color(gname, theme)
        group_parts.append(
            f'<rect x="{gx:.1f}" y="{gy:.1f}" width="{gw:.1f}" '
            f'height="{gh:.1f}" rx="10" fill="{_tint(color, theme)}" '
            f'stroke="{_tint(color, theme, 0.5)}" stroke-width="1"/>')
        # Label goes on the TOP layer (group_labels appended after nodes):
        # in-background labels ended up hidden behind nodes.
        group_labels.append(
            f'<text x="{gx + 8:.1f}" y="{gy + 17:.1f}" font-size="13" '
            f'font-weight="bold" letter-spacing="2" fill="{_tint(color, theme, 0.85)}" '
            f'stroke="{T["bg"]}" stroke-width="3"></text>'
            f'<text x="{gx + 8:.1f}" y="{gy + 17:.1f}" font-size="13" '
            f'font-weight="bold" letter-spacing="2" fill="{_tint(color, theme, 0.85)}">'
            f'{_esc(gname.upper())}</text>')

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-family="sans-serif">',
        f'<rect width="100%" height="100%" fill="{T["bg"]}"/>',
        f'<text x="8" y="16" font-size="13" fill="{T['title']}">{title}</text>',
    ]
    parts.extend(group_parts)

    # layout['edges'] preserves graph_json['edges'] order in every engine.
    # Arrowheads are explicit polygons, NOT <marker> defs: ImageMagick's SVG
    # rasterizer silently drops markers, so the shared PNGs lost every arrow.
    for edge, meta in zip(layout['edges'], graph_json['edges']):
        color = _edge_color(meta.get('ingredient', ''), theme)
        pts = ' '.join(f'{tx(x):.1f},{ty(y):.1f}' for x, y in edge['points'])
        # Recycling edges (DFS back edges) are dashed so loops read as loops.
        dash = ' stroke-dasharray="6,4"' if meta.get('back') else ''
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                     f'stroke-width="1.2" stroke-opacity="{T['edge_opacity']}"{dash}/>')
        parts.append(_arrowhead(edge['points'], color, tx, ty))

    for nid, (x, y) in layout['nodes'].items():
        w, h = layout['sizes'][nid]
        kind = kind_of.get(nid, 'machine')
        parts.append(
            f'<rect x="{tx(x) - w / 2:.1f}" y="{ty(y) - h / 2:.1f}" '
            f'width="{w:.1f}" height="{h:.1f}" rx="4" '
            f'fill="{T['fill'][kind]}" stroke="{T['stroke'][kind]}"/>')
        lines = lines_of.get(nid, [])
        line_h = h / max(len(lines), 1)
        top = ty(y) - h / 2
        for i, line in enumerate(lines):
            weight = ' font-weight="bold"' if line['k'] == 'name' else ''
            fill = LINE_FILL.get(line['k'], '#111')
            parts.append(
                f'<text x="{tx(x):.1f}" y="{top + line_h * (i + 0.5) + 4:.1f}" '
                f'font-size="11" text-anchor="middle" fill="{fill}"{weight}>'
                f'{_esc(line["t"])}</text>')

    # Edge rate labels LAST so nodes can't cover them (multi-input/output
    # machines need the per-edge rate to disambiguate). Anchor a fixed
    # distance back from the arrowhead along the polyline — a fraction of
    # the final segment lands on the node when clipping leaves a stub.
    for edge, meta in zip(layout['edges'], graph_json['edges']):
        if not edge.get('label') or len(edge['points']) < 2:
            continue
        color = _edge_color(meta.get('ingredient', ''), theme)
        lx, ly, vx, vy = _walk_back(edge['points'], 16.0)
        # Perpendicular offset so the text sits beside the line.
        anchor = 'start' if vy != 0 else ('end' if vx < 0 else 'start')
        off_x = 3 if vy != 0 else (-3 if vx < 0 else 3)
        common = (f'x="{tx(lx) + off_x:.1f}" y="{ty(ly) - 3:.1f}" '
                  f'font-size="8" text-anchor="{anchor}"')
        # Two-pass halo (stroked copy under filled copy): renderer-agnostic,
        # unlike paint-order which e.g. ImageMagick ignores.
        parts.append(f'<text {common} fill="{T['bg']}" stroke="{T['bg']}" '
                     f'stroke-width="2.5" stroke-opacity="0.85">'
                     f'{edge["label"]}</text>')
        parts.append(f'<text {common} fill="{color}">{edge["label"]}</text>')

    parts.extend(group_labels)
    parts.append('</svg>')
    return '\n'.join(parts)


def _arrowhead(points, color, tx, ty, length=7.0, half_width=3.0):
    """Filled triangle at the polyline end, oriented along the approach."""
    import math
    if len(points) < 2:
        return ''
    # Direction from the last non-degenerate segment.
    x2, y2 = points[-1]
    for i in range(len(points) - 2, -1, -1):
        x1, y1 = points[i]
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg > 1e-6:
            break
    else:
        return ''
    ux, uy = (x2 - x1) / seg, (y2 - y1) / seg
    bx, by = x2 - ux * length, y2 - uy * length
    px, py = -uy, ux
    p1 = (tx(x2), ty(y2))
    p2 = (tx(bx + px * half_width), ty(by + py * half_width))
    p3 = (tx(bx - px * half_width), ty(by - py * half_width))
    return (f'<polygon points="{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} '
            f'{p3[0]:.1f},{p3[1]:.1f}" fill="{color}"/>')


def _walk_back(points, distance):
    """Point `distance` before the arrow end, walking along the polyline;
    returns (x, y, dir_x, dir_y) with the local segment direction."""
    import math
    remaining = distance
    for i in range(len(points) - 1, 0, -1):
        (x1, y1), (x2, y2) = points[i - 1], points[i]
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg >= remaining and seg > 1e-9:
            t = 1 - remaining / seg
            return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t,
                    (x2 - x1) / seg, (y2 - y1) / seg)
        remaining -= seg
    (x1, y1), (x2, y2) = points[0], points[-1]
    seg = math.hypot(x2 - x1, y2 - y1) or 1.0
    return (x1, y1, (x2 - x1) / seg, (y2 - y1) / seg)


def _esc(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))
