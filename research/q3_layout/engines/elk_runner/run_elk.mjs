// Reads a layout request on stdin, prints ELK's layout on stdout.
// Request: { graph: interchange-json, style: "layered" | "orthogonal",
//            extraOptions?: { ... } }
// Nodes with a `group` field become children of a compound node, so
// subgraphs are packed BY the layout engine, not drawn post hoc.
import ELK from 'elkjs';

const elk = new ELK();

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const { graph, style, extraOptions } = JSON.parse(Buffer.concat(chunks).toString());

// Defaults from the tuning grids (research.md): DEPTH_FIRST cycle breaking
// halves crossings on recycle-loop-heavy charts; thoroughness 30 +
// NETWORK_SIMPLEX layering + post-compaction beat the ELK defaults on
// crossings, area and crossing clusters. NETWORK_SIMPLEX node placement is
// the one option that blows up at scale — BRANDES_KOEPF above 300 nodes.
const big = graph.nodes.length > 300;
const layoutOptions = {
  'elk.algorithm': 'layered',
  'elk.direction': 'DOWN',
  'elk.layered.spacing.nodeNodeBetweenLayers': '45',
  'elk.spacing.nodeNode': '25',
  'elk.edgeRouting': style === 'orthogonal' ? 'ORTHOGONAL' : 'SPLINES',
  'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
  'elk.layered.cycleBreaking.strategy': 'DEPTH_FIRST',
  'elk.layered.thoroughness': '30',
  'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
  'elk.layered.nodePlacement.strategy': big ? 'BRANDES_KOEPF' : 'NETWORK_SIMPLEX',
  'elk.layered.compaction.postCompaction.strategy': 'LEFT_RIGHT_CONSTRAINT_LOCKING',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  ...(extraOptions ?? {}),
};

const groups = new Map();
const topChildren = [];
for (const n of graph.nodes) {
  const child = { id: n.id, width: n.w, height: n.h };
  if (n.group) {
    if (!groups.has(n.group)) {
      groups.set(n.group, {
        id: `group:${n.group}`,
        children: [],
        layoutOptions: {
          'elk.padding': '[top=28,left=12,bottom=12,right=12]',
        },
      });
    }
    groups.get(n.group).children.push(child);
  } else {
    topChildren.push(child);
  }
}

const elkGraph = {
  id: 'root',
  layoutOptions,
  children: [...groups.values(), ...topChildren],
  edges: graph.edges.map((e) => ({ id: e.id, sources: [e.src], targets: [e.dst] })),
};

const out = await elk.layout(elkGraph);

// Node coordinates are relative to the parent; walk with offsets.
const nodes = {};
const groupRects = {};
function walk(node, ox, oy) {
  for (const child of node.children ?? []) {
    const ax = (child.x ?? 0) + ox;
    const ay = (child.y ?? 0) + oy;
    if (child.id.startsWith('group:')) {
      groupRects[child.id.slice(6)] = [ax, ay, child.width, child.height];
      walk(child, ax, ay);
    } else {
      nodes[child.id] = [ax + child.width / 2, ay + child.height / 2];
      walk(child, ax, ay);
    }
  }
}
walk(out, 0, 0);

// With INCLUDE_CHILDREN, elkjs moves edges into their proper container and
// reports section coordinates RELATIVE TO IT — collect with accumulated
// offsets or intra-group edges render as stubs at the origin.
// elkjs leaves edges where they were declared (the root), but with
// INCLUDE_CHILDREN their section coordinates are relative to the edge's
// COMPUTED container — the LCA of its endpoints. With one nesting level:
// intra-group edges are group-relative, everything else root-relative.
const parentGroup = new Map();
for (const g of groups.values()) {
  for (const child of g.children) parentGroup.set(child.id, g.id.slice(6));
}
function edgeOffset(e) {
  const gs = parentGroup.get(e.sources[0]);
  const gt = parentGroup.get(e.targets[0]);
  if (gs && gs === gt && groupRects[gs]) {
    return [groupRects[gs][0], groupRects[gs][1]];
  }
  return [0, 0];
}
const edges = (out.edges ?? []).map((e) => {
  const [ox, oy] = edgeOffset(e);
  const pts = [];
  for (const sec of e.sections ?? []) {
    pts.push([sec.startPoint.x + ox, sec.startPoint.y + oy]);
    for (const bp of sec.bendPoints ?? []) pts.push([bp.x + ox, bp.y + oy]);
    pts.push([sec.endPoint.x + ox, sec.endPoint.y + oy]);
  }
  return { id: e.id, points: pts };
});

process.stdout.write(JSON.stringify({ nodes, edges, groups: groupRects }));
