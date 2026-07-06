// Reads a layout request on stdin, prints ELK's layout on stdout.
// Request: { graph: interchange-json, style: "layered" | "orthogonal" }
import ELK from 'elkjs';

const elk = new ELK();

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const { graph, style, extraOptions } = JSON.parse(Buffer.concat(chunks).toString());

// Defaults from the palladium_line/230_platline tuning grid (research.md):
// thoroughness 30 + NETWORK_SIMPLEX layering/placement + post-compaction
// beat the ELK defaults on crossings (-12..35%), area (-20..46%) and
// crossing clusters, for <2s on those charts. NETWORK_SIMPLEX node
// placement is the one option that blows up at scale (DNF >60s at 394
// machines, vs 3.8s without) — fall back to BRANDES_KOEPF on big graphs.
const big = graph.nodes.length > 300;
const layoutOptions = {
  'elk.algorithm': 'layered',
  'elk.direction': 'DOWN',
  'elk.layered.spacing.nodeNodeBetweenLayers': '45',
  'elk.spacing.nodeNode': '25',
  'elk.edgeRouting': style === 'orthogonal' ? 'ORTHOGONAL' : 'SPLINES',
  'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
  // DEPTH_FIRST cycle breaking halves crossings on recycle-loop-heavy
  // factory charts (palladium_line 215->108, 230_platline 13->6): the
  // default GREEDY breaker reverses the wrong edges and smears loops
  // across layers.
  'elk.layered.cycleBreaking.strategy': 'DEPTH_FIRST',
  'elk.layered.thoroughness': '30',
  'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
  'elk.layered.nodePlacement.strategy': big ? 'BRANDES_KOEPF' : 'NETWORK_SIMPLEX',
  'elk.layered.compaction.postCompaction.strategy': 'LEFT_RIGHT_CONSTRAINT_LOCKING',
  ...(extraOptions ?? {}),
};

const elkGraph = {
  id: 'root',
  layoutOptions,
  children: graph.nodes.map((n) => ({ id: n.id, width: n.w, height: n.h })),
  edges: graph.edges.map((e) => ({ id: e.id, sources: [e.src], targets: [e.dst] })),
};

const out = await elk.layout(elkGraph);

const nodes = {};
for (const child of out.children) {
  nodes[child.id] = [child.x + child.width / 2, child.y + child.height / 2];
}
const edges = (out.edges ?? []).map((e) => {
  const pts = [];
  for (const sec of e.sections ?? []) {
    pts.push([sec.startPoint.x, sec.startPoint.y]);
    for (const bp of sec.bendPoints ?? []) pts.push([bp.x, bp.y]);
    pts.push([sec.endPoint.x, sec.endPoint.y]);
  }
  return { id: e.id, points: pts };
});

process.stdout.write(JSON.stringify({ nodes, edges }));
