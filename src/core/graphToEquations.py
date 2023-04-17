import networkx as nx
from pulp import LpProblem, LpMinimize, LpVariable

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

            for in_edge in in_edges:
                for out_edge in out_edges:
                    # Look up relationship in Machine node
                    in_edge_ingredient = G.get_edge_data(*in_edge)[0]['object'].name
                    out_edge_ingredient = G.get_edge_data(*out_edge)[0]['object'].name
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
                ==
                0
            )

            # Add connected ExternalNodes to objective function
            for in_edge in in_edges:
                parent_obj = G.nodes[in_edge[0]]['object']
                if isinstance(parent_obj, ExternalNode):
                    objective_function += edge_to_variable[in_edge]
            for out_edge in out_edges:
                child_obj = G.nodes[out_edge[1]]['object']
                if isinstance(child_obj, ExternalNode):
                    objective_function += edge_to_variable[out_edge]
    
    if not isinstance(objective_function, int):
        problem += objective_function

    return problem, edge_to_variable
