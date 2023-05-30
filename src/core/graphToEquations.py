import networkx as nx
import sympy
from pulp import LpProblem, LpMaximize, LpMinimize, LpVariable

from src.data.basicTypes import EdgeData, ExternalNode, IngredientNode, MachineNode


def constructPuLPFromGraph(G: nx.MultiDiGraph) -> LpProblem:
    problem = LpProblem('GTNH_Flowchart', LpMinimize)
    objective_function = 0

    edge_to_variable = {}
    variable_index = 0

    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, MachineNode):
            # Construct machine-internal equations
            in_edges = G.in_edges(idx)
            out_edges = G.out_edges(idx)

            for edge_list in [in_edges, out_edges]:
                for edge in edge_list:
                    edge_to_variable[edge] = LpVariable(f'x{variable_index}', lowBound=0, cat='Continuous')
                    variable_index += 1
            
            if len(in_edges) == 0 or len(out_edges) == 0:
                continue

            print(in_edges)

            for in_edge in in_edges:
                for out_edge in out_edges:
                    # Look up relationship in Machine node
                    # Need to do this kind of indexing because MultiDiGraph edges can look like [(from_node, to_node, which_one)]
                    if len(in_edge) == 3:
                        in_edge_ingredient = G.edges[in_edge[0], in_edge[1], in_edge[2]]['object'].name
                    else:
                        in_edge_ingredient = G.edges[in_edge[0], in_edge[1], 0]['object'].name
                    if len(out_edge) == 3:
                        out_edge_ingredient = G.edges[out_edge[0], out_edge[1], out_edge[2]]['object'].name
                    else:
                        out_edge_ingredient = G.edges[out_edge[0], out_edge[1], 0]['object'].name
                    constant_multiple = nobj.O[out_edge_ingredient] / nobj.I[in_edge_ingredient]

                    # Add to problem definition
                    problem += (
                        edge_to_variable[in_edge] * constant_multiple 
                        - edge_to_variable[out_edge]
                        == 0
                    )
    
    for idx, node in G.nodes.items():
        # At this point all variable edge -> index relations are constructed
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            # Construct ingredient equality equations
            in_edges = G.in_edges(idx)
            out_edges = G.out_edges(idx)
            if len(in_edges) == 0 or len(out_edges) == 0:
                continue

            # Total I/O for ingredient
            problem += (
                sum([edge_to_variable[in_edge] for in_edge in in_edges])
                +
                sum([-edge_to_variable[out_edge] for out_edge in out_edges])
                >=
                0
            )

            # Add connected ExternalNodes to objective function
            for in_edge in in_edges:
                # Source
                parent_obj = G.nodes[in_edge[0]]['object']
                if isinstance(parent_obj, ExternalNode):
                    objective_function += 10000000* edge_to_variable[in_edge]
            for out_edge in out_edges:
                # Sink
                child_obj = G.nodes[out_edge[1]]['object']
                if isinstance(child_obj, ExternalNode):
                    objective_function += 10000000* edge_to_variable[out_edge]
    
    # Add maximum flow objective function
    # This is the best as it minimizes the amount of external ingredients used
    for edge_idx, _ in G.edges.items():
        edge = edge_idx[:2]
        from_node, to_node = edge
        if not isinstance(G.nodes[from_node]['object'], ExternalNode) and not isinstance(G.nodes[to_node]['object'], ExternalNode):
            objective_function += edge_to_variable[edge]

    if not isinstance(objective_function, int):
        problem += objective_function

    return problem, edge_to_variable


def constructSymPyFromGraph(G: nx.MultiDiGraph, construct_slack: bool=True):
    system_of_equations = []
    variable_index = 0
    edge_to_variable = {}

    for idx, node in G.nodes.items():
        nobj = node['object']
        if isinstance(nobj, MachineNode):
            # Construct machine-internal equations
            in_edges = G.in_edges(idx)
            out_edges = G.out_edges(idx)

            for edge_list in [in_edges, out_edges]:
                for edge in edge_list:
                    edge_to_variable[edge] = sympy.symbols(f'x{variable_index}', positive=True, real=True)
                    variable_index += 1
            
            if len(in_edges) == 0 or len(out_edges) == 0:
                continue

            for in_edge in in_edges:
                for out_edge in out_edges:
                    # Look up relationship in Machine node
                    # Need to do this kind of indexing because MultiDiGraph edges can look like [(from_node, to_node, which_one)]
                    if len(in_edge) == 3:
                        in_edge_ingredient = G.edges[in_edge[0], in_edge[1], in_edge[2]]['object'].name
                    else:
                        in_edge_ingredient = G.edges[in_edge[0], in_edge[1], 0]['object'].name
                    if len(out_edge) == 3:
                        out_edge_ingredient = G.edges[out_edge[0], out_edge[1], out_edge[2]]['object'].name
                    else:
                        out_edge_ingredient = G.edges[out_edge[0], out_edge[1], 0]['object'].name
                    constant_multiple = sympy.Rational(nobj.O[out_edge_ingredient], nobj.I[in_edge_ingredient])

                    # Add to problem definition
                    system_of_equations.append(
                        edge_to_variable[in_edge] * constant_multiple 
                        - edge_to_variable[out_edge]
                    )
    
    ingredient_to_slack_variable = {}
    for idx, node in G.nodes.items():
        # At this point all variable edge -> index relations are constructed
        nobj = node['object']
        if isinstance(nobj, IngredientNode):
            # Construct ingredient equality equations
            # Additionally, add a slack variable for each ingredient
            in_edges = G.in_edges(idx)
            out_edges = G.out_edges(idx)
            if len(in_edges) == 0 or len(out_edges) == 0:
                continue

            if construct_slack:
                slack_variable = sympy.symbols(f's{variable_index}', real=True)
                ingredient_to_slack_variable[nobj.name] = slack_variable
                variable_index += 1

            # Total I/O for ingredient
            system_of_equations.append(
                sum([edge_to_variable[in_edge] for in_edge in in_edges])
                +
                sum([-edge_to_variable[out_edge] for out_edge in out_edges])
                +
                slack_variable if construct_slack else 0
            )

    return system_of_equations, edge_to_variable, ingredient_to_slack_variable
