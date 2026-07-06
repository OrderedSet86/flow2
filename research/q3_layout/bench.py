"""Layout benchmark: corpus x engines x styles -> SVG renders + metrics.csv
+ an HTML gallery for side-by-side visual comparison.

Run: uv run python -m research.q3_layout.bench [--case NAME]
"""

import argparse
import csv
import json
import re
import signal
import subprocess
import time
from pathlib import Path

from research.common.corpus import list_cases
from research.q3_layout.interchange import solved_graph_json
from research.q3_layout.metrics import all_metrics
from research.q3_layout.render import to_svg

RENDERS = Path(__file__).parent / 'renders'
ENGINE_TIMEOUT_S = 45      # per user feedback: > 60s is useless
# (ogdf orthogonal auto-switches to its fast planarizer above 300 nodes —
# ~15s at 394 machines plus ~4s cppyy subprocess startup.)

# PNGs are for sharing (Discord); skip renders whose pixel area would make
# rasterization slow and the file unpostable (i.e. nanocircuits-scale).
PNG_MAX_PIXELS = 60e6
PNG_PARALLEL = 8


def export_pngs(svg_paths):
    """Rasterize SVGs to sibling .png files, in parallel, size-guarded."""
    jobs = []
    for svg in svg_paths:
        head = svg.read_text()[:200]
        m = re.search(r'width="(\d+)" height="(\d+)"', head)
        if m and int(m.group(1)) * int(m.group(2)) > PNG_MAX_PIXELS:
            print(f'  png skipped (too large): {svg.name}')
            continue
        jobs.append(svg)
    running = []
    for svg in jobs:
        running.append(subprocess.Popen(
            ['convert', str(svg), str(svg.with_suffix('.png'))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        if len(running) >= PNG_PARALLEL:
            running.pop(0).wait()
    for proc in running:
        proc.wait()
    return len(jobs)


class _Timeout(Exception):
    pass


def _alarm(*_):
    raise _Timeout()


def _engines():
    from research.q3_layout.engines.dot_engine import layout as dot
    from research.q3_layout.engines.elk_engine import layout as elk
    from research.q3_layout.engines.grandalf_engine import layout as grandalf
    engines = {'dot': dot, 'elk': elk, 'grandalf': grandalf}
    try:
        from research.q3_layout.engines.ogdf_engine import layout as ogdf
        engines['ogdf'] = ogdf
    except Exception as exc:      # cppyy is fragile; run without it
        print(f'! ogdf unavailable: {type(exc).__name__}: {exc}')
    return engines


COMBOS = [('dot', 'layered'), ('elk', 'layered'), ('elk', 'orthogonal'),
          ('ogdf', 'layered'), ('ogdf', 'orthogonal'),
          ('grandalf', 'layered')]


def run(case_names, png=True):
    engines = _engines()
    rows = []
    svg_paths = []
    for name in case_names:
        gj = solved_graph_json(name)
        out_dir = RENDERS / name.replace('/', '__')
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'graph.json').write_text(json.dumps(gj, indent=1))
        for engine, style in COMBOS:
            if engine not in engines:
                continue
            key = f'{engine}_{style}'
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(ENGINE_TIMEOUT_S)
            try:
                t0 = time.perf_counter()
                lay = engines[engine](gj, style)
                wall = time.perf_counter() - t0
            except _Timeout:
                print(f'  {name} {key}: TIMEOUT (> {ENGINE_TIMEOUT_S}s)')
                rows.append({'case': name, 'engine': engine, 'style': style,
                             'status': 'timeout'})
                continue
            except Exception as exc:
                print(f'  {name} {key}: ERROR {type(exc).__name__}: '
                      f'{str(exc)[:120]}')
                rows.append({'case': name, 'engine': engine, 'style': style,
                             'status': 'error'})
                continue
            finally:
                signal.alarm(0)
            m = all_metrics(lay)
            m.update({'case': name, 'engine': engine, 'style': style,
                      'status': 'ok', 'seconds': round(wall, 3),
                      'nodes': len(gj['nodes']), 'edges': len(gj['edges'])})
            rows.append(m)
            svg = to_svg(lay, gj, f'{name} — {engine} {style} — '
                                  f'{m["crossings"]} crossings')
            svg_path = out_dir / f'{key}.svg'
            svg_path.write_text(svg)
            svg_paths.append(svg_path)
            print(f'  {name} {key}: x={m["crossings"]} bends={m["bends"]} '
                  f'{wall:.2f}s')
    if png:
        n = export_pngs(svg_paths)
        print(f'  rasterized {n} PNGs')
    return rows


def write_outputs(rows):
    fields = ['case', 'engine', 'style', 'status', 'nodes', 'edges',
              'crossings', 'bends', 'edge_length', 'area', 'aspect',
              'node_overlaps', 'crossing_clusters', 'parallel_bundles',
              'seconds']
    with open(RENDERS / 'metrics.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in fields})

    by_case = {}
    for row in rows:
        by_case.setdefault(row['case'], []).append(row)

    html = ['<!doctype html><meta charset="utf-8">',
            '<title>flowv2 layout benchmark</title>',
            '<style>body{font-family:sans-serif;margin:20px}'
            '.case{margin-bottom:48px}.grid{display:flex;flex-wrap:wrap;'
            'gap:12px}.cell{border:1px solid #ccc;padding:8px;'
            'max-width:460px}.cell img{max-width:440px;max-height:420px;'
            'display:block}table{border-collapse:collapse;font-size:12px}'
            'td,th{border:1px solid #ddd;padding:2px 6px;text-align:right}'
            'caption,th:first-child,td:first-child{text-align:left}</style>',
            '<h1>Layout benchmark</h1>',
            '<p>Same solved graph, same renderer — only node positions and '
            'edge routes differ. Click an image for full size.</p>']
    for case, case_rows in by_case.items():
        slug = case.replace('/', '__')
        html.append(f'<div class="case"><h2>{case}</h2>')
        html.append('<table><tr><th>engine/style</th><th>crossings</th>'
                    '<th>x-clusters</th><th>bundles</th>'
                    '<th>bends</th><th>edge len</th><th>area</th>'
                    '<th>aspect</th><th>seconds</th></tr>')
        for row in case_rows:
            if row['status'] != 'ok':
                html.append(f'<tr><td>{row["engine"]} {row["style"]}</td>'
                            f'<td colspan="8">{row["status"]}</td></tr>')
                continue
            html.append(
                f'<tr><td>{row["engine"]} {row["style"]}</td>'
                f'<td>{row["crossings"]}</td>'
                f'<td>{row["crossing_clusters"]}</td>'
                f'<td>{row["parallel_bundles"]}</td>'
                f'<td>{row["bends"]}</td>'
                f'<td>{row["edge_length"]}</td><td>{row["area"]}</td>'
                f'<td>{row["aspect"]}</td><td>{row["seconds"]}</td></tr>')
        html.append('</table><div class="grid">')
        for row in case_rows:
            if row['status'] != 'ok':
                continue
            rel = f'{slug}/{row["engine"]}_{row["style"]}.svg'
            png = RENDERS / slug / f'{row["engine"]}_{row["style"]}.png'
            png_link = (f' <a href="{slug}/{png.name}">png</a>'
                        if png.exists() else '')
            html.append(f'<div class="cell"><a href="{rel}">'
                        f'<img src="{rel}" loading="lazy"></a>'
                        f'<div>{row["engine"]} {row["style"]}{png_link}</div></div>')
        html.append('</div></div>')
    (RENDERS / 'index.html').write_text('\n'.join(html))
    print(f'\nwrote {RENDERS / "metrics.csv"} and {RENDERS / "index.html"}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', help='single case instead of full corpus')
    parser.add_argument('--no-png', action='store_true',
                        help='skip PNG rasterization')
    args = parser.parse_args()
    names = [args.case] if args.case else list_cases()
    write_outputs(run(names, png=not args.no_png))
