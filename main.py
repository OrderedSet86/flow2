from pathlib import Path

import networkx as nx
from pulp import PULP_CBC_CMD

from src.core.addUserLocking import addUserChosenQuantityFromFlow1Yaml
from src.core.connectGraph import produceConnectedGraphFromDisjoint, addExternalNodes
from src.core.flow1Compat import constructDisjointGraphFromFlow1Yaml
from src.core.graphToEquations import constructPuLPFromGraph
from src.core.postProcessing import pruneZeroEdges
from src.data.basicTypes import IngredientNode, MachineNode


if __name__ == '__main__':
    # flow_projects_path = Path('~/Dropbox/OrderedSetCode/game-optimization/minecraft/flow/projects').expanduser()
    # yaml_path = flow_projects_path / 'power/oil/light_fuel_hydrogen_loop.yaml'
    yaml_path = Path('temporaryFlowProjects/jet_fuel.yaml')

    G = constructDisjointGraphFromFlow1Yaml(yaml_path)
    G = produceConnectedGraphFromDisjoint(G)
    G = addExternalNodes(G)
    for idx, node in G.nodes.items():
        print(idx, node)
    
    # TODO:
    # Remove extremely common / ignorable resources, like water

    # Construct PuLP representation of graph
    problem, edge_to_variable = constructPuLPFromGraph(G)
    # There isn't a chosen quantity yet, so add one
    # The YAML file has one since this is Flow1 compatible, so get it from there
    problem = addUserChosenQuantityFromFlow1Yaml(G, edge_to_variable, problem, yaml_path)
    
    print(problem)

    seed = 1337 # Choose a seed for reproduceability
    status = problem.solve(PULP_CBC_CMD(msg=True, options = [f'RandomS {seed}']))
    print(status)

    G = pruneZeroEdges(G, edge_to_variable)

    if status == 1:
        for variable in edge_to_variable.values():
            print(variable, variable.value())

    # Add label for ease of reading
    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, MachineNode):
            node['label'] = nobj.machine
            node['color'] = 'green'
        elif isinstance(nobj, IngredientNode):
            node['label'] = nobj.name
            node['color'] = 'red'
        node['shape'] = 'box'
        node['label'] = f"({idx}) {node['label']}"
    
    for idx, edge in G.edges.items():
        index_idx = idx[:2]
        label_parts = [str(edge_to_variable[index_idx])]
        if status == 1:
            label_parts.append(f'{edge_to_variable[index_idx].value():.2f}')
        edge['label'] = '\n'.join(label_parts)


    ag = nx.nx_agraph.to_agraph(G)
    ag.draw('proto.pdf', prog='dot')