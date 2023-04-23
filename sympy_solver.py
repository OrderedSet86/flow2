from pathlib import Path

import networkx as nx
from sympy import linsolve

from src.core.addUserLocking import addSympyUserChosenQuantityFromFlow1Yaml
from src.core.connectGraph import produceConnectedGraphFromDisjoint
from src.core.flow1Compat import constructDisjointGraphFromFlow1Yaml
from src.core.graphToEquations import constructSymPyFromGraph
from src.core.postProcessing import pruneZeroEdges
from src.core.preProcessing import addExternalNodes, removeIgnorableIngredients
from src.data.basicTypes import ExternalNode, IngredientNode, MachineNode


def sympyVarToIndex(var):
    return int(var.name[1:])


if __name__ == '__main__':
    # flow_projects_path = Path('~/Dropbox/OrderedSetCode/game-optimization/minecraft/flow/projects').expanduser()
    # yaml_path = flow_projects_path / 'power/oil/light_fuel_hydrogen_loop.yaml'
    yaml_path = Path('temporaryFlowProjects/jet_fuel.yaml')

    G = constructDisjointGraphFromFlow1Yaml(yaml_path)
    G = produceConnectedGraphFromDisjoint(G)
    G = removeIgnorableIngredients(G) # eg water
    for idx, node in G.nodes.items():
        print(idx, node)

    # Construct SymPy representation of graph
    system_of_equations, edge_to_variable, ingredient_to_slack_variable = constructSymPyFromGraph(G)
    system_of_equations = addSympyUserChosenQuantityFromFlow1Yaml(G, edge_to_variable, system_of_equations, yaml_path)
    print()
    print('=====PROBLEM=====')
    for eq in system_of_equations:
        print(f'{eq} = 0')
    print()

    all_variables = list(edge_to_variable.values()) + list(ingredient_to_slack_variable.values())
    res = linsolve(system_of_equations, *all_variables)
    print('=====SOLUTION=====')
    for idx, eq in enumerate(res.args[0]):
        if idx < len(edge_to_variable):
            print(f'x{idx} = {eq}')
        else:
            print(f's{idx} = {eq}')

    # Add label for ease of reading
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, ExternalNode):
            node['label'] = nobj.machine
            node['color'] = 'purple'
        elif isinstance(nobj, MachineNode):
            node['label'] = nobj.machine
            if nobj.machine.startswith('[Source]') or nobj.machine.startswith('[Sink]'):
                node['color'] = 'purple'
            else:
                node['color'] = 'green'
        elif isinstance(nobj, IngredientNode):
            if nobj.name in ingredient_to_slack_variable:
                node['label'] = f'{nobj.name} ({ingredient_to_slack_variable[nobj.name]})'
            else:
                node['label'] = nobj.name
            node['color'] = 'red'
        node['shape'] = 'box'
        node['label'] = f"({idx}) {node['label']}"
        node['fontname'] = 'arial'
    
    for idx, edge in G.edges.items():
        index_idx = idx[:2]
        label_parts = [str(edge_to_variable[index_idx])]
        # FIXME:
        if len(res) > 0:
            label_parts.append(f'{res.args[0][sympyVarToIndex(edge_to_variable[index_idx])]}')
        edge['label'] = '\n'.join(label_parts)
        edge['fontname'] = 'arial'

    ag = nx.nx_agraph.to_agraph(G)
    ag.draw('proto.png', prog='dot')