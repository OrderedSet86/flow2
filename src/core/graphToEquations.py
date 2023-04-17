import networkx as nx
from pulp import LpProblem, LpMinimize, LpVariable

from src.data.basicTypes import EdgeData, IngredientNode, MachineNode


def constructPuLPFromGraph(G: nx.MultiDiGraph) -> LpProblem:
    problem = LpProblem('GTNH_Flowchart', LpMinimize)

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
        if isinstance(nobj, IngredientNode):
            # Construct ingredient equality equations
            in_edges = G.in_edges(idx)
            out_edges = G.out_edges(idx)
            problem += (
                sum([edge_to_variable[in_edge] for in_edge in in_edges])
                -
                sum([edge_to_variable[out_edge] for out_edge in out_edges])
                ==
                0
            )
    
    return problem, edge_to_variable
