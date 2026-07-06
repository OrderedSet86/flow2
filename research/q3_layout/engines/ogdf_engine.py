"""OGDF via a subprocess worker (see ogdf_worker.py for why): errors arrive
as real Python exceptions with the C++ stderr attached, and timeouts
actually kill the process instead of waiting for a C++ call to return.

styles: 'layered' (Sugiyama), 'orthogonal' (planarization, full quality),
plus opts for the fast/relaxed variants.
"""

import json
import select
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = 'research.q3_layout.engines.ogdf_worker'
DEFAULT_TIMEOUT_S = 120


# Above this size, full variable-embedding planarization is infeasible
# (DNF at 394 machines); the fast planarizer finishes it in ~15s with the
# best crossing count of any engine at that size.
ORTHO_FAST_THRESHOLD = 300

_worker = None


def _get_worker():
    """Persistent JSONL worker: pays the ~4s cppyy JIT startup once per
    session instead of once per layout call."""
    global _worker
    if _worker is None or _worker.poll() is not None:
        _worker = subprocess.Popen(
            [sys.executable, '-m', WORKER, '--serve'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, cwd=REPO_ROOT)
    return _worker


def _worker_call(request: dict, timeout_s: float) -> dict:
    global _worker
    worker = _get_worker()
    worker.stdin.write(json.dumps(request) + '\n')
    worker.stdin.flush()
    ready, _, _ = select.select([worker.stdout], [], [], timeout_s)
    if not ready:
        worker.kill()
        _worker = None
        raise TimeoutError(f'ogdf worker exceeded {timeout_s}s')
    line = worker.stdout.readline()
    if not line:          # worker died (segfault etc.)
        stderr = worker.stderr.read() if worker.stderr else ''
        _worker = None
        raise RuntimeError(f'ogdf worker crashed:\n{stderr.strip()[-800:]}')
    out = json.loads(line)
    if 'error' in out:
        raise RuntimeError(f'ogdf layout error:\n{out["error"].strip()[-800:]}')
    return out


def layout(graph_json: dict, style: str = 'layered', opts: dict = None,
           timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    opts = dict(opts or {})
    if style == 'orthogonal' and 'ortho_quality' not in opts:
        opts['ortho_quality'] = ('fast' if len(graph_json['nodes'])
                                 > ORTHO_FAST_THRESHOLD else 'good')
    out = _worker_call({'graph': graph_json, 'style': style, 'opts': opts},
                       timeout_s)

    sizes = {n['id']: (n['w'], n['h']) for n in graph_json['nodes']}
    nodes = {nid: tuple(xy) for nid, xy in out['nodes'].items()}
    by_id = {e['id']: e for e in out['edges']}
    edges = []
    for edge in graph_json['edges']:
        pts = [tuple(p) for p in by_id[edge['id']]['points']]
        edges.append({'points': pts, 'src': edge['src'], 'dst': edge['dst'],
                      'label': edge['label']})
    from research.q3_layout.engines.clip import clip_layout
    # OGDF endpoints are node centers; clip so arrowheads are visible.
    return clip_layout({'nodes': nodes, 'sizes': sizes, 'edges': edges,
                        'engine': 'ogdf', 'style': style})
