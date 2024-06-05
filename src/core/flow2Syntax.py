
from pathlib import Path

import networkx as nx
import yaml
from networkx import MultiDiGraph
from typing import Union

from src.data.basicTypes import EdgeData, IngredientNode, MachineNode


def applyNoSource(
        G: MultiDiGraph,
        edge_to_variable,
        system_of_equations,
        yaml_path: Union[str, Path],
        user_dict: dict,
    ): # outputs system of equations

    for no_source_ingredient in user_dict['no_source']:
        for idx, node in G.nodes.items():
            nobj = node['object']
            if isinstance(nobj, IngredientNode):
                if nobj.name == no_source_ingredient and nobj.associated_slack_variable is not None:
                    system_of_equations.append(
                        nobj.associated_slack_variable # = 0
                    )
    
    return system_of_equations


def applyWhitelistedSlackVariables(
        G: MultiDiGraph,
        edge_to_variable,
        system_of_equations,
        yaml_path: Union[str, Path],
        user_dict: dict,
    ):
    # Set all slack variables other than user defined to 0
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            if nobj.associated_slack_variable is not None and nobj.name not in user_dict['whitelisted_slack_variables']:
                system_of_equations.append(
                    nobj.associated_slack_variable # = 0
                )
    
    return system_of_equations


known_v2_options = {
    'no_source': applyNoSource,
    'whitelisted_slack_variables': applyWhitelistedSlackVariables,
}


def applyV2UserOptions(
        G: MultiDiGraph,
        edge_to_variable,
        system_of_equations,
        yaml_path: Union[str, Path]
    ): # outputs system of equations

    # Get user options from YAML file
    with open(yaml_path, 'r') as f:
        conf = yaml.safe_load(f)
    
    for user_dict in conf:
        if 'v2_node_type' in user_dict:
            node_type = user_dict['v2_node_type']
            if node_type in known_v2_options:
                fxn = known_v2_options[node_type]
                system_of_equations = fxn(G, edge_to_variable, system_of_equations, yaml_path, user_dict)

    return system_of_equations