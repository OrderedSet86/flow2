from collections import defaultdict
from pathlib import Path

import networkx as nx
from typing import Union

from src.core.sharedYamlLoad import loadYamlFile
from src.data.basicTypes import EdgeData, IngredientNode, MachineNode


def constructDisjointGraphFromFlow1Yaml(yaml_path: Union[str, Path], ) -> nx.MultiDiGraph:
    conf = loadYamlFile(yaml_path)

    # MultiDiGraph = DiGraph, but self edges and parallel edges are allowed
    G = nx.MultiDiGraph()
    node_id = 0

    for machine_dict in conf:
        # Add machine nodes
        machine_node_id = node_id
        relevant_attrs = ['m', 'I', 'O', 'eut', 'dur']

        if not all([x in machine_dict for x in relevant_attrs]):
            # v2 style nodes
            continue

        construction_list = [machine_dict[x] for x in relevant_attrs]
        G.add_node(node_id, object=MachineNode(*construction_list))
        node_id += 1

        # Add ingredient nodes
        for direction in ['I', 'O']:
            for ingredient_name, ingredient_quantity in machine_dict[direction].items():
                G.add_node(node_id, object=IngredientNode(ingredient_name, ingredient_quantity, direction, machine_node_id))
                if direction == 'I':
                    G.add_edge(machine_node_id, node_id, object=EdgeData(ingredient_name, ingredient_quantity))
                elif direction == 'O':
                    G.add_edge(node_id, machine_node_id, object=EdgeData(ingredient_name, ingredient_quantity))
                node_id += 1

    return G


def getGroupsFromFlow1Yaml(yaml_path: Union[str, Path]) -> dict:
    conf = loadYamlFile(yaml_path)

    groups = defaultdict(list)
    for machine_dict in conf:
        if 'group' in machine_dict:
            groups[machine_dict['group']].append(machine_dict)

    return groups