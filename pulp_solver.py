from pathlib import Path

import networkx as nx
from pulp import PULP_CBC_CMD

from src.core.addUserLocking import addPulpUserChosenQuantityFromFlow1Yaml
from src.core.connectGraph import produceConnectedGraphFromDisjoint
from src.core.flow1Compat import constructDisjointGraphFromFlow1Yaml
from src.core.graphToEquations import constructPuLPFromGraph
from src.core.postProcessing import pruneZeroEdges
from src.core.preProcessing import addExternalNodes, removeIgnorableIngredients
from src.data.basicTypes import ExternalNode, IngredientNode, MachineNode


if __name__ == '__main__':
    # flow_projects_path = Path('~/Dropbox/OrderedSetCode/game-optimization/minecraft/flow/projects').expanduser()
    # yaml_path = flow_projects_path / 'power/oil/light_fuel_hydrogen_loop.yaml'
    yaml_path = Path('temporaryFlowProjects/microsheep.yaml')

    G = constructDisjointGraphFromFlow1Yaml(yaml_path)
    G = produceConnectedGraphFromDisjoint(G)
    G = removeIgnorableIngredients(G) # eg water
    G = addExternalNodes(G)
    for idx, node in G.nodes.items():
        print(idx, node)
    
    # Construct PuLP representation of graph
    system_of_equations, edge_to_variable = constructPuLPFromGraph(G)
    # for edge, variable in edge_to_variable.items():
    #     # Warm start all non-ExternalNode edges to 1
    #     if not isinstance(G.nodes[edge[0]]['object'], ExternalNode) and not isinstance(G.nodes[edge[1]]['object'], ExternalNode):
    #         variable.setInitialValue(1)

    # There isn't a chosen quantity yet, so add one
    # The YAML file has one since this is Flow1 compatible, so get it from there
    system_of_equations = addPulpUserChosenQuantityFromFlow1Yaml(G, edge_to_variable, system_of_equations, yaml_path)
    
    print(system_of_equations)

    seed = 1337 # Choose a seed for reproduceability
    status = system_of_equations.solve(PULP_CBC_CMD(msg=True, warmStart=True, options = [f'RandomS {seed}']))
    print(status)

    G = pruneZeroEdges(G, edge_to_variable)

    if status == 1:
        for variable in edge_to_variable.values():
            print(variable, variable.value())

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
            node['label'] = nobj.name
            node['color'] = 'red'
        node['shape'] = 'box'
        node['label'] = f"({idx}) {node['label']}"
        node['fontname'] = 'arial'
    
    for idx, edge in G.edges.items():
        index_idx = idx[:2]
        label_parts = [str(edge_to_variable[index_idx])]
        if status == 1:
            label_parts.append(f'{edge_to_variable[index_idx].value():.2f}')
        edge['label'] = '\n'.join(label_parts)
        edge['fontname'] = 'arial'

    ag = nx.nx_agraph.to_agraph(G)
    ag.draw('proto.png', prog='dot')