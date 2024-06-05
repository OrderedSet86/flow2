from pathlib import Path

import networkx as nx
import numpy as np
import sympy

from src.core.addUserLocking import addSympyUserChosenQuantityFromFlow1Yaml
from src.core.connectGraph import produceConnectedGraphFromDisjoint
from src.core.flow1Compat import constructDisjointGraphFromFlow1Yaml
from src.core.flow2Syntax import applyV2UserOptions
from src.core.graphToEquations import constructSymPyFromGraph
from src.core.postProcessing import pruneZeroEdges
from src.core.preProcessing import addExternalNodes, removeIgnorableIngredients
from src.data.basicTypes import ExternalNode, IngredientNode, MachineNode
from v1_utils import userAccurate


def sympyVarToIndex(var):
    return int(var.name[1:])


if __name__ == '__main__':
    # flow_projects_path = Path('~/Dropbox/OrderedSetCode/game-optimization/minecraft/flow/projects').expanduser()
    # yaml_path = flow_projects_path / 'power/oil/light_fuel_hydrogen_loop.yaml'
    yaml_path = Path('temporaryFlowProjects/palladium_line.yaml')

    G = constructDisjointGraphFromFlow1Yaml(yaml_path)
    G = produceConnectedGraphFromDisjoint(G)
    G = removeIgnorableIngredients(G) # eg water
    for idx, node in G.nodes.items():
        print(idx, node)

    # Construct SymPy representation of graph
    system_of_equations, edge_to_variable, ingredient_to_slack_variable = constructSymPyFromGraph(G, construct_slack=True)
    system_of_equations = addSympyUserChosenQuantityFromFlow1Yaml(G, edge_to_variable, system_of_equations, yaml_path)
    all_variables = list(edge_to_variable.values()) + list(ingredient_to_slack_variable.values())

    system_of_equations = applyV2UserOptions(G, edge_to_variable, system_of_equations, yaml_path)

    # # TEMPORARY
    # if yaml_path == Path('temporaryFlowProjects/palladium_line.yaml'):
    #     no_external_input = [
    #         'reprecipitated palladium dust',
    #         'palladium metallic powder dust',
    #         'palladium salt dust',
    #         'palladium enriched ammonia',
    #         'platinum concentrate',
    #     ]
    #     for ing in no_external_input:
    #         system_of_equations.append(
    #             ingredient_to_slack_variable[ing] # = 0
    #         )

    # Compute how over or underdetermined the system is
    # Can't just compare number of equations to number of variables because some equations are linear combinations of others
    # So we need to compute the rank of the linear system of equation's matrix
    # def constructMatrix(system_of_equations):
    #     matrix = []
    #     for eq in system_of_equations:
    #         row = []
    #         for var in all_variables:
    #             row.append(float(eq.coeff(var)))
            
    #         # Check for constant term
    #         constant = eq.func(*[term for term in eq.args if not term.free_symbols])
    #         row.append(float(constant))

    #         matrix.append(row)
    #     return np.array(matrix)

    # mat = constructMatrix(system_of_equations)
    # rank = np.linalg.matrix_rank(mat)
    # print(mat)
    # print(f'Rank of system: {rank}')
    # print(f'Number of variables: {len(all_variables)}')
    # if rank < len(all_variables):
    #     raise NotImplementedError('System is underdetermined')

    # Try setting slack variables to 0 or skipping if already a number
    # This gives us at least one purely numerical solution
    # slack_index_to_slack_variable = list(ingredient_to_slack_variable.values())

    # res = None
    # first = True
    # while first or any(isinstance(eq, (sympy.core.add.Add, sympy.core.symbol.Symbol)) for eq in res.args[0]):
    #     first = False
    #     res = sympy.linsolve(system_of_equations, *all_variables)
    #     if isinstance(res, sympy.sets.sets.EmptySet):
    #         system_of_equations.pop()
    #         break
    #     else:
    #         for sidx, eq in enumerate(res.args[0][-len(ingredient_to_slack_variable):]):
    #             if isinstance(eq, (sympy.core.add.Add, sympy.core.symbol.Symbol)):
    #                 system_of_equations.append(slack_index_to_slack_variable[sidx]) # == 0
    #                 break

    print()
    print('=====PROBLEM=====')
    for eq in system_of_equations:
        print(f'{eq} = 0')
    print()

    res = sympy.linsolve(system_of_equations, *all_variables)
    print('=====SOLUTION=====')
    for idx, eq in enumerate(res.args[0]):
        if idx < len(edge_to_variable):
            print(f'x{idx} = {eq}')
        else:
            print(f's{idx} = {eq}')

    # Add source/sink nodes based on slack variables
    node_idx = max(G.nodes.keys()) + 1
    for idx, node in list(G.nodes.items()):
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            if nobj.associated_slack_variable is not None:
                slack_value = res.args[0][sympyVarToIndex(nobj.associated_slack_variable)]
                if isinstance(slack_value, sympy.core.numbers.Number) and slack_value != 0:
                    # Add source or sink node
                    if slack_value > 0:
                        # Source
                        source_name = f'[Source] {nobj.name}'
                        node_name = node_idx
                        G.add_node(len(G.nodes), object=ExternalNode(source_name, {}, {}, 0, 1))
                        G.add_edge(node_name, idx, object=None)
                        edge_to_variable[(node_name, idx)] = sympy.symbols(f'x{node_idx}', positive=True, real=True)
                    elif slack_value < 0:
                        # Sink
                        sink_name = f'[Sink] {nobj.name}'
                        node_name = node_idx
                        G.add_node(len(G.nodes), object=ExternalNode(sink_name, {}, {}, 0, 1))
                        G.add_edge(idx, node_name, object=None)
                        edge_to_variable[(idx, node_name)] = sympy.symbols(f'x{node_idx}', positive=True, real=True)
                    node_idx += 1

    # node_idx = max(G.nodes.keys()) + 1
    # for idx, node in list(G.nodes.items()):
    #     nobj = node['object']
    #     if isinstance(nobj, IngredientNode):
    #         if nobj.name in ingredient_to_slack_variable:
    #             slack_value = res.args[0][sympyVarToIndex(ingredient_to_slack_variable[nobj.name])]

    #             node_name = node_idx
    #             if slack_value > 0:
    #                 machine_name = f'[Source] {nobj.name}'
    #                 G.add_node(node_name, object=ExternalNode(machine_name, {}, {}, 0, 1))
    #                 G.add_edge(node_name, idx, object=None)
    #                 edge_to_variable[(node_name, idx)] = ingredient_to_slack_variable[nobj.name]
    #             elif slack_value < 0:
    #                 machine_name = f'[Sink] {nobj.name}'
    #                 G.add_node(node_name, object=ExternalNode(machine_name, {}, {}, 0, 1))
    #                 G.add_edge(idx, node_name, object=None)
    #                 edge_to_variable[(idx, node_name)] = ingredient_to_slack_variable[nobj.name]
    #             node_idx += 1

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
        if len(res) > 0:
            raw_equation_on_edge = res.args[0][sympyVarToIndex(edge_to_variable[index_idx])]
            if isinstance(raw_equation_on_edge, (sympy.core.numbers.Integer, sympy.core.numbers.Rational)):
                raw_equation_on_edge = userAccurate(float(raw_equation_on_edge))
            # print(type(raw_equation_on_edge), raw_equation_on_edge, round(float(raw_equation_on_edge), 4))
            equation_on_edge = f'{raw_equation_on_edge}'
            label_parts.append(equation_on_edge)
        edge['label'] = '\n'.join(label_parts)
        edge['fontname'] = 'arial'

    ag = nx.nx_agraph.to_agraph(G)
    ag.draw('proto.pdf', prog='dot')