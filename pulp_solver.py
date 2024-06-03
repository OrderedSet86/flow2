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
    yaml_path = Path('temporaryFlowProjects/palladium_line.yaml')

    G = None

    # Helper function that solves the current problem (reloads, forms graph, forms equations, solves) with some sources excluded.
    def solve(do_print=False, excluded_sources=set()):
        G = constructDisjointGraphFromFlow1Yaml(yaml_path)
        G = produceConnectedGraphFromDisjoint(G)
        G = removeIgnorableIngredients(G) # eg water
        G = addExternalNodes(G, excluded_sources)
        if do_print:
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

        # Add known constraint equations

        if do_print:
            print(system_of_equations)

        seed = 1337 # Choose a seed for reproduceability

        status = system_of_equations.solve(PULP_CBC_CMD(msg=do_print, warmStart=True, options = [f'RandomS {seed}']))
        if do_print:
            print(status)

        return G, status, edge_to_variable

    # A crude function that analyses the solved variables and counts how many are nonzero - i.e. not redundant.
    def count_used_variables(edge_to_variable):
        eps = 1e-6
        c = 0
        for edge, var in edge_to_variable.items():
            if abs(var.value()) < eps:
                c += 1
        return len(edge_to_variable) - c

    # Sometimes illformed models can return variables that are None, we need to reject those.
    def is_any_variable_none(edge_to_variable):
        for edge, var in edge_to_variable.items():
            if var.value() is None:
                return True
        return False

    # This can definitely be done better, computed in batch for all, etc.
    # But this works. Returns the amount of the given resource that's sources from an external node. We need to know if it's non-zero.
    def get_source_usage(G, source_name, edge_to_variable):
        usage = 0
        for ingnode_idx, node in list(G.nodes.items()):
            nobj = node['object']
            if isinstance(nobj, IngredientNode):
                if nobj.name == source_name:
                    in_edges = G.in_edges(ingnode_idx)
                    for in_edge in in_edges:
                        # Source
                        parent_obj = G.nodes[in_edge[0]]['object']
                        if isinstance(parent_obj, ExternalNode):
                            usage += edge_to_variable[in_edge].value()

        return usage

    def get_source_coeff(G, source_name):
        for idx, node in G.nodes.items():
            # At this point all variable edge -> index relations are constructed
            nobj = node['object']
            if isinstance(nobj, IngredientNode):
                if nobj.name != source_name:
                    continue

                # Construct ingredient equality equations
                in_edges = G.in_edges(idx)
                out_edges = G.out_edges(idx)
                if len(in_edges) == 0 or len(out_edges) == 0:
                    continue

                # Add connected ExternalNodes to objective function
                has_non_external_sources = False
                for in_edge in in_edges:
                    # Source
                    parent_obj = G.nodes[in_edge[0]]['object']
                    if not isinstance(parent_obj, ExternalNode):
                        has_non_external_sources = True
                        break

                # If the source is the only way to get the given ingredient then we assign a smaller weight,
                # because we only want to prevent sourcing products that can be made internally.
                source_coeff = 1e9 if has_non_external_sources else 1e3
                return source_coeff

        return None

    # Initial solution with all edges.
    G, status, edge_to_variable = solve(True)

    # If success, we try to iteratively remove some sources, as long as we can,
    # hoping that we will arrive at a solution that utilizes the whole production chain
    # and doesn't just source the final ingredients.
    if status == 1:
        # Identify all sources in the graph. We will be trying to remove them.
        source_names = []
        for idx, node in G.nodes.items():
            nobj = node['object']
            if isinstance(nobj, IngredientNode):
                source_names.append(nobj.name)

        last_num_used_variables = count_used_variables(edge_to_variable)

        # We want to check the sources that have a high coefficient first.
        # These are the ingredients that can also be produced internally.
        source_names.sort(key=lambda x: -get_source_coeff(G, x))

        # Initially we don't exclude anything.
        excluded_sources = set()

        while True:
            # Redundant on first iteration, but whatever.
            G, status, edge_to_variable = solve(True, excluded_sources)

            # We loop infinitely until no more changes to the graph can be made.
            # The algorithm is guaranteed to halt because there is a finite amount
            # of edges to remove.
            any_change = False
            for source_name in source_names:
                # Only attempt removal of sources that are currently in use.
                # Otherwise we could potentially remove a useful source.
                if get_source_usage(G, source_name, edge_to_variable) < 1e-6:
                    continue

                # Speculatively exclude the source
                excluded_sources.add(source_name)
                # And compute the new graph, with this source excluded (and all previous exclusions too).
                new_G, new_status, new_edge_to_variable = solve(False, excluded_sources)

                print(source_name, new_status, is_any_variable_none(new_edge_to_variable))
                if new_status != 1 or is_any_variable_none(new_edge_to_variable):
                    # If there is no solution we restore the previous excluded_sources and try the next source
                    excluded_sources.remove(source_name)
                else:
                    num_used_variables = count_used_variables(new_edge_to_variable)
                    if num_used_variables > last_num_used_variables:
                        last_num_used_variables = num_used_variables

                        # If there is a solution then we can safely remove the source, as it's not essential.
                        any_change = True

                        # Remove the source from the list as we don't need to check it again.
                        source_names.remove(source_name)

                        print(f'Excluded {source_name}.')

                        # We have to redo the iteration as the source_names set changed while we're iterating it.
                        break
                    else:
                        excluded_sources.remove(source_name)

            if not any_change:
                break

        print(f'Excluded sources: {excluded_sources}.')
        G, status, edge_to_variable = solve(True, excluded_sources)

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
    ag.draw('proto.pdf', prog='dot')