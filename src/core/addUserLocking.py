from pathlib import Path
from typing import Union

import yaml
from networkx import MultiDiGraph
from pulp import LpProblem, LpVariable

from src.data.basicTypes import IngredientNode, MachineNode


def addUserChosenQuantityFromFlow1Yaml(
        G: MultiDiGraph,
        edge_to_variable: dict[tuple, LpVariable],
        problem: LpProblem,
        yaml_path: Union[str, Path]
    ):
    with open(yaml_path, 'r') as f:
        conf = yaml.safe_load(f)

    # Create machine_index: node index mapping
    machine_index_to_node_index = {}
    machine_index = 0
    for node_idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, MachineNode):
            machine_index_to_node_index[machine_index] = node_idx
            machine_index += 1

    # Create ingredient name: node index mapping
    ingredient_name_to_node_index = {}
    for node_idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            ingredient_name_to_node_index[nobj.name] = node_idx

    print(machine_index_to_node_index)

    # Add locking equation to LpProblem
    for machine_index, machine_dict in enumerate(conf):
        node_idx = machine_index_to_node_index[machine_index]
        nobj = G.nodes[node_idx]['object']
        if 'number' in machine_dict:
            # Pick the first item quantity and lock it
            # I could lock everything, but the others can be inferred directly from the first
            if len(nobj.I) > 0:
                ingredient_name = list(nobj.I.keys())[0]
                edge = (ingredient_name_to_node_index[ingredient_name], node_idx)
                problem += edge_to_variable[edge] == machine_dict['number'] # FIXME:
            elif len(nobj.O) > 0:
                ingredient_name = list(nobj.O.keys())[0]
                edge = (node_idx, ingredient_name_to_node_index[ingredient_name])
                problem += edge_to_variable[edge] == machine_dict['number'] # FIXME:
            else:
                raise RuntimeError('Attempt to lock machine that has no inputs or outputs')
            print(f'added "number" locking equation for {ingredient_name} on {edge}')

        elif 'target' in machine_dict:
            # Target is a dict of ingredient: quantity_per_s

            # Construct dict of ingredient_name: [direction, quantity]
            ingredient_lookup = {}
            for direction in ['I', 'O']:
                for ingredient_name, ingredient_quantity in getattr(nobj, direction).items():
                    ingredient_lookup[ingredient_name] = [direction, ingredient_quantity]

            # Look up quantities being referred to
            target = machine_dict['target']
            for target_name, target_quantity in target.items():
                direction, base_quantity = ingredient_lookup[target_name]
                if direction == 'I':
                    edge = (ingredient_name_to_node_index[target_name], node_idx)
                elif direction == 'O':
                    edge = (node_idx, ingredient_name_to_node_index[target_name])
                problem += edge_to_variable[edge] == target_quantity # FIXME:
            
            print(f'added "target" locking equation for {target_name} on {edge}')

    return problem