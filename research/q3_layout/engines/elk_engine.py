"""ELK (elkjs) via a node subprocess. ELK is Java-native — of all engines
here it has the best porting story for PlanNH; elkjs is the same codebase
transpiled, so results carry over.
"""

import json
import subprocess
from pathlib import Path

RUNNER = Path(__file__).parent / 'elk_runner' / 'run_elk.mjs'


def layout(graph_json: dict, style: str = 'layered') -> dict:
    request = json.dumps({'graph': graph_json, 'style': style})
    proc = subprocess.run(['node', str(RUNNER)], input=request,
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f'elk runner failed: {proc.stderr[:500]}')
    out = json.loads(proc.stdout)

    sizes = {n['id']: (n['w'], n['h']) for n in graph_json['nodes']}
    nodes = {nid: tuple(xy) for nid, xy in out['nodes'].items()}

    by_id = {e['id']: e for e in out['edges']}
    edges = []
    for edge in graph_json['edges']:
        pts = [tuple(p) for p in by_id[edge['id']]['points']]
        if not pts:      # degenerate: straight line fallback
            pts = [nodes[edge['src']], nodes[edge['dst']]]
        edges.append({'points': pts, 'src': edge['src'], 'dst': edge['dst'],
                      'label': edge['label']})
    return {'nodes': nodes, 'sizes': sizes, 'edges': edges,
            'engine': 'elk', 'style': style}
