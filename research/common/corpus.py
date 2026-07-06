"""Corpus loader: wraps the existing src.core pipeline so every experiment
sees exactly the same graphs, water-removal behavior, and pin semantics.
"""

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from src.core.connectGraph import produceConnectedGraphFromDisjoint
from src.core.flow1Compat import constructDisjointGraphFromFlow1Yaml
from src.core.preProcessing import addExternalNodes, removeIgnorableIngredients
from src.core.sharedYamlLoad import loadYamlFile
from src.data.basicTypes import IngredientNode, MachineNode

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / 'temporaryFlowProjects'

MACHINE_ATTRS = ('m', 'I', 'O', 'eut', 'dur')


@dataclass
class Pin:
    kind: str        # 'number' | 'target'
    edge: tuple      # (u, v) node indices in the connected graph
    ingredient: str
    value: float
    machine_yaml_index: int


@dataclass
class Case:
    name: str
    path: Path
    graph: nx.MultiDiGraph          # connected, water removed, externals added
    pins: list                      # list[Pin]
    v2_options: dict                # {'no_source': [...], 'whitelisted_slack_variables': [...]}

    def target_pins(self):
        return [p for p in self.pins if p.kind == 'target']

    def number_pins(self):
        return [p for p in self.pins if p.kind == 'number']


def list_cases(include_tests: bool = True) -> list:
    names = []
    for p in sorted(CORPUS_DIR.glob('*.yaml')):
        names.append(p.stem)
    if include_tests:
        for p in sorted((CORPUS_DIR / 'testProjects').glob('*.yaml')):
            names.append(f'testProjects/{p.stem}')
    return names


def _case_path(name: str) -> Path:
    path = CORPUS_DIR / f'{name}.yaml'
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _resolve_pins(G: nx.MultiDiGraph, conf: list) -> list:
    """Return neutral (edge, value) pins from the YAML.

    'number' means "run N of this machine" (gtnh-flow v1 semantics): the
    locked edge flow is per_craft_qty * N / dur. The existing addUserLocking
    code pins the edge to the raw N (its own FIXME) — that shrank light_fuel
    by 25x and made the machine floors bind, conjuring phantom sources.
    'target' locks the named ingredient's edge at that machine to the given
    rate directly.
    """
    machine_index_to_node = {}
    machine_index = 0
    for node_idx, node in G.nodes.items():
        if isinstance(node['object'], MachineNode):
            machine_index_to_node[machine_index] = node_idx
            machine_index += 1

    ingredient_to_node = {}
    for node_idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            ingredient_to_node[nobj.name] = node_idx

    pins = []
    machine_index = 0
    for yaml_index, machine_dict in enumerate(conf):
        if not all(attr in machine_dict for attr in MACHINE_ATTRS):
            continue  # v2 style node
        node_idx = machine_index_to_node[machine_index]
        machine_index += 1
        nobj = G.nodes[node_idx]['object']

        if 'number' in machine_dict:
            available = {ing for ing in list(nobj.I) + list(nobj.O)
                         if ing in ingredient_to_node}
            candidates = [ing for ing in list(nobj.I) if ing in available] or \
                         [ing for ing in list(nobj.O) if ing in available]
            if not candidates:
                raise RuntimeError(f'cannot lock machine {nobj.m}: no lockable edges')
            ing = candidates[0]
            if ing in nobj.I:
                edge = (ingredient_to_node[ing], node_idx)
                per_craft = nobj.I[ing]
            else:
                edge = (node_idx, ingredient_to_node[ing])
                per_craft = nobj.O[ing]
            rate = per_craft * machine_dict['number'] / nobj.dur
            pins.append(Pin('number', edge, ing, rate, yaml_index))

        elif 'target' in machine_dict:
            for target_name, target_quantity in machine_dict['target'].items():
                if target_name in nobj.I:
                    edge = (ingredient_to_node[target_name], node_idx)
                elif target_name in nobj.O:
                    edge = (node_idx, ingredient_to_node[target_name])
                else:
                    raise RuntimeError(
                        f'target {target_name} not an ingredient of machine {nobj.m}')
                pins.append(Pin('target', edge, target_name,
                                target_quantity, yaml_index))
    return pins


def _v2_options(conf: list) -> dict:
    options = {}
    for entry in conf:
        if isinstance(entry, dict) and 'v2_node_type' in entry:
            key = entry['v2_node_type']
            options[key] = entry.get(key, [])
    return options


def load_case(name: str, with_externals: bool = True,
              excluded_sources: set = frozenset()) -> Case:
    path = _case_path(name)
    G = constructDisjointGraphFromFlow1Yaml(path)
    G = produceConnectedGraphFromDisjoint(G)
    G = removeIgnorableIngredients(G)
    if with_externals:
        G = addExternalNodes(G, set(excluded_sources))
    conf = loadYamlFile(path)
    pins = _resolve_pins(G, conf)
    return Case(name=name, path=path, graph=G, pins=pins,
                v2_options=_v2_options(conf))
