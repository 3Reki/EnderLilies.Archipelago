from __future__ import annotations

import json
import re
import os
from Locations import locations as l
from StartingLocations import startingLocationsData as starts
from LocationMapping import LOCATION_MAPPING # LocationMapping imported from poptracker's locationMapping.lua

from typing import Dict, List, Set, Tuple, Union

class ParsingTreeNode:
    type: str # max or min
    parent: ParsingTreeNode
    children: list[Union[str, ParsingTreeNode]]

    def __init__(self, parent, type=""):
        self.parent = parent
        self.type = type
        self.children = []
    
    def get_depth(self):
        if self.parent == None:
            return 0
        return self.parent.get_depth() + 1

def rule_to_lua(rule: str, caller=None, logic_tokens=[]) -> str:
    global macros, item_aliases, nodes_aliases, region_aliases, nodes_connection_path

    # Tokenization
    if len(logic_tokens) == 0:
        logic_pattern = r"\b[a-zA-Z0-9_,]+\b|\(|\)|\||\+"
        logic_tokens = re.findall(logic_pattern, rule)
    
    conversion = {
        "(" : "(",
        ")" : ")",
        "+" : " and ",
        "|" : " or ",
    }

    lua_rule = ""
    for token in logic_tokens:
        if token in conversion:
            lua_rule += conversion[token]
        elif token in macros:
            lua_rule += f"{convert_macro_name(token)}()"
        elif token in nodes_aliases:
            lua_rule += f'getLocAccess("{nodes_connection_path[token]}")'
        elif token in item_aliases:
            lua_rule += f'has("{item_aliases[token]}")'
        elif token in region_aliases:
            lua_rule += f'getLocAccess("{nodes_connection_path[token]}")'
        else:
            lua_rule += f"s.has('{token}', p) -- error"

    return lua_rule

def rule_to_lua2(tree_node:ParsingTreeNode, caller:str) -> str:
    global macros, item_aliases, nodes_aliases, region_aliases, nodes_connection_path

    lua_rule = ""

    if tree_node.type == "max":
        lua_rule += "math.max("
    elif tree_node.type == "min":
        lua_rule += "math.min("
    else:
        print("Error : Node has no type. Caller : " + caller)

    for i in range(0, len(tree_node.children)):
        if i > 0:
            lua_rule += ", "
        
        token = tree_node.children[i]
        if isinstance(token, str):
            if token in macros:
                lua_rule += f"{convert_macro_name(token)}_A()"
            elif token in nodes_aliases:
                lua_rule += f'getAccess("{nodes_connection_path[token]}")'
            elif token in item_aliases:
                lua_rule += f'getAccess("{item_aliases[token]}")'
            elif token.split(',')[0] in item_aliases:
                split_token = token.split(',')
                lua_rule += f'getAccess("{item_aliases[split_token[0]]}", {split_token[1]})'
            elif token in region_aliases:
                lua_rule += f'getAccess("{nodes_connection_path[token]}")'
            else:
                print(f"Error while parsing token {token} for function {caller}")
                lua_rule += f"getAccess('{token}') -- error"

        else:
            lua_rule += rule_to_lua2(token, caller)
        
    lua_rule += ")"
    return lua_rule

def parse_rule_bis(logic_tokens:list, treeNode:ParsingTreeNode, cur_id:int, parenthesis_nesting:list[ParsingTreeNode]):
    def add_to_node_IF(node:ParsingTreeNode, token:str):
        if token not in "()":
            node.children.append(token)

    if cur_id >= len(logic_tokens):
        add_to_node_IF(treeNode, logic_tokens[cur_id - 1])
        return
    
    if logic_tokens[cur_id] == '(':
        treeNode.children.append(ParsingTreeNode(treeNode))
        parenthesis_nesting.append(treeNode)
        parse_rule_bis(logic_tokens, treeNode.children[-1], cur_id + 1, parenthesis_nesting)

    elif logic_tokens[cur_id] == ')':
        add_to_node_IF(treeNode, logic_tokens[cur_id - 1])
        parenthesis_node = parenthesis_nesting.pop()
        parse_rule_bis(logic_tokens, parenthesis_node, cur_id + 1, parenthesis_nesting)
    
    elif logic_tokens[cur_id] == '+':
        if treeNode.type == "max":
            new_node = ParsingTreeNode(treeNode, "min")
            if logic_tokens[cur_id - 1] == ")":
                treeNode.children[-1].parent = new_node
                new_node.children.append(treeNode.children.pop())
            else:
                new_node.children.append(logic_tokens[cur_id - 1])
            treeNode.children.append(new_node)
            parse_rule_bis(logic_tokens, new_node, cur_id + 1, parenthesis_nesting)
        else:
            treeNode.type = "min"
            add_to_node_IF(treeNode, logic_tokens[cur_id - 1])
            parse_rule_bis(logic_tokens, treeNode, cur_id + 1, parenthesis_nesting)
    
    elif logic_tokens[cur_id] == '|':
        if treeNode.type == "min":
            add_to_node_IF(treeNode, logic_tokens[cur_id - 1])
            if (treeNode.parent.type != "max"):
                new_node = ParsingTreeNode(treeNode.parent, "max")
                new_node.children.append(treeNode)
                treeNode.parent.children[-1] = new_node
                treeNode.parent = new_node
            else:
                new_node = treeNode.parent
            parse_rule_bis(logic_tokens, new_node, cur_id + 1, parenthesis_nesting)
        else:
            treeNode.type = "max"
            add_to_node_IF(treeNode, logic_tokens[cur_id - 1])
            parse_rule_bis(logic_tokens, treeNode, cur_id + 1, parenthesis_nesting)
    
    else:
        parse_rule_bis(logic_tokens, treeNode, cur_id + 1, parenthesis_nesting)


def parse_rule(rule: str, caller=None) -> str:
    global macros, item_aliases, nodes_aliases, region_aliases, connections

    # Tokenization
    logic_pattern = r"\b[a-zA-Z0-9_,]+\b|\(|\)|\||\+"
    logic_tokens = re.findall(logic_pattern, rule)

    location_indexes = []
    for i in range (0, len(logic_tokens)):
        if logic_tokens[i] in nodes_aliases or logic_tokens[i] in region_aliases:
            location_indexes.append(i)

    if len(logic_tokens) == 1:
        if len(location_indexes) != 1:
            print("Weird ? " + rule)

        return rule_to_lua(rule, caller)

    rule_tree = ParsingTreeNode(None)
    rule_tree.children.append(ParsingTreeNode(rule_tree))
    p_nesting = []
    parse_rule_bis(logic_tokens, rule_tree.children[0], 0, p_nesting)

    if (len(p_nesting) > 0):
        print(f"Something wrong happened while parsing parenthesis for rule '{rule}'. ")

    return rule_to_lua2(rule_tree.children[0], caller)


def get_lua_func(func_name, return_cond, additional_code = "") -> str:
    lua_func =  "function " + func_name + "()\n"
    lua_func += additional_code
    lua_func += "  return " + return_cond + "\n"
    lua_func += "end\n"
    return lua_func

def convert_macro_name(macro) -> str:
    macro_name = macro
    if macro[0] >= '0' and macro[0] <= '9':
        macro_name = macro[1:] + macro[0]
    return macro_name

def get_function_name(node_name) -> str:
    global special_names, reverse_tags, reverse_nodes

    # edge cases
    if node_name in special_names:
        return special_names[node_name]
    
    # For most room transitions
    if node_name in reverse_tags:
        if reverse_tags[node_name] in reverse_nodes:
            return reverse_nodes[reverse_tags[node_name]]
    
    if node_name in locs:
        return locs[node_name]
    
    print(f"Warning : Using default node name for {node_name}. No alternative was found")
    return node_name

def get_associated_func(map_name, location_name, section_name) -> str:

    mapping_name = f"@{map_name}/{location_name}/{section_name}"

    mapped_address = None
    for address, mapping in LOCATION_MAPPING.items():
        if mapping_name == mapping:
            mapped_address = address
            break
    
    if mapped_address == None:
        print(f"Error: {mapping_name} not found in LOCATION_MAPPING")
        return "Error"
    
    node_name = None
    for _, loc_data in l.items():
        if mapped_address == loc_data.address:
            node_name = loc_data.key
            break
    
    if node_name == None:
        print(f"Error: {mapping_name}'s address not found in locations")
        return "Error"
    
    return "^$" + get_function_name(node_name)
    


if __name__ == "__main__":
    json_path               = "worlds/enderlilies/tools/EnderLilies.Randomizer.json"
    poptracker_json_path    = "worlds/enderlilies/tools/PoptrackerProperties.json"
    generated_lua_path      = "worlds/enderlilies/tools/output/generated.lua"
    output_connection_json  = "worlds/enderlilies/tools/output/connections.json"
    # Put all poptracker's location json in this folder to convert them
    locations_folder_path   = "worlds/enderlilies/tools/output/locations"


    ########################## FILL IN DATA ##########################

    with open(json_path, "r") as f:
        data = json.load(f)

    with open(poptracker_json_path, "r") as f:
        pop_data = json.load(f)

    excludes = {s for s in pop_data["exclude"]}
    exclude_on_duplicate = {s for s in pop_data["exclude_on_duplicate"]}
    special_names = {key:value for key, value in pop_data["special_names"].items()}
    missing_connections = {key:value for key, value in pop_data["missing_connections"].items()}
    additional_rules = {key:value for key, value in pop_data["additional_rules"].items()}
    nodes_connection_path = {key:value for key, value in pop_data["nodes_connection_path"].items()}

    item_aliases = {alias:item for alias, item in pop_data["items_alias"].items()}
    nodes_aliases = {}
    region_aliases = {}

    connections = {}
    reverse_tags = {tag:alias for alias, tag in data["tags"].items()}
    reverse_nodes = {}

    macros : Dict[str, any] = {name:rule for name, rule in data["macros"].items()}

    for alias, node in data["nodes_alias"].items():
        if node.startswith("Map."):
            region_aliases[alias] = node
        else:
            nodes_aliases[alias] = node
        reverse_nodes[node] = alias
    
    for name1, name2 in additional_rules.items():
        if not name1 in region_aliases:
            region_aliases[name1] = None
        if not name2 in region_aliases:
            region_aliases[name2] = None

    # Find connections
    for node_name, node in data["nodes"].items():
        # One ways
        if node_name in special_names: 
            continue

        if "content" in node:
            if node["content"].startswith("Map."):
                # if "WorldTravelVolume" in node_name:
                    if node_name in reverse_tags:
                        connections[reverse_nodes[reverse_tags[node_name]]] = reverse_nodes[node["content"]]
                    else:
                        print(f"Error : node_name {node_name} not found in tags")
                # else -> resting point, should handle here ?
        else:
            # some resting points
            print(f"Warning : node {node_name} doesn't have content")
    
    for a, b in missing_connections.items():
        connections[a] = b
        connections[b] = a

    for name, rule in data["macros"].items():
        macros[name] = rule

    
    ######################## FILL IN LOCATIONS #######################

    locs = {}

    for name, d in l.items():
        if d.key:
            if d.key in excludes:
                locs[d.key] = None
                continue

            if d.address in LOCATION_MAPPING:
                splitted_key = d.key.split("_")
                splitted_mapping = LOCATION_MAPPING[d.address].split('/')
                # regex : trim " '-,+" characters and (...) sequences
                trimmed = re.sub(r"([ '\-,+]|\(.*\))*","",splitted_mapping[-1])

                loc_name = f"{splitted_key[0]}{splitted_key[1]}{trimmed}"

                if (loc_name in exclude_on_duplicate and loc_name in locs.values()):
                    locs[d.key] = None
                    continue

                same_name_count = 0
                while loc_name in locs.values():
                    print(f"{loc_name} already in values ! Renaming...")
                    same_name_count += 1
                    loc_name = f'{re.sub(r"_[0-9]*$","",loc_name)}_{same_name_count}'

                locs[d.key] = loc_name
            else:
                locs[d.key] = name

    
    ######################## OUTPUT GENERATORS #######################

    def create_generated_lua():
        with open(generated_lua_path, "w") as generated_lua:
            print(f"--[ Logic was generated from DataExtractor script, see https://github.com/3Reki/EnderLilies.Archipelago/tree/PoptrackerExporter ]--\n", file=generated_lua)
            
            for macro, rule in macros.items():
                macro_name = convert_macro_name(macro)
                lua_rule = rule_to_lua(rule)

                print(get_lua_func(macro_name, lua_rule), file=generated_lua)
                func_body = f"  if {lua_rule} then\n"
                func_body += "    return AccessibilityLevel.Normal\n"
                func_body += "  end\n"
                print(get_lua_func(macro_name + "_A", "AccessibilityLevel.None", func_body), file=generated_lua)

            rules = {}
            for node_name, node in data["nodes"].items():
                func_name = get_function_name(node_name)

                if func_name == None:
                    continue

                is_start_loc = node_name in reverse_nodes and any([reverse_nodes[node_name] == item.clientKey for item in starts.values()])
                if 'rules' in node:
                    lua_rule = parse_rule(f"{reverse_nodes[node_name]} | {node['rules']}" if is_start_loc else node['rules'], func_name)
                elif is_start_loc:
                    lua_rule = rule_to_lua(reverse_nodes[node_name])
                else:
                    lua_rule = "True"

                rules[func_name] = lua_rule
            
            for func_name, rule in rules.items():
                if (func_name in connections):
                    print(get_lua_func(func_name, rules[connections[func_name]]), file=generated_lua)
                else:
                    print(get_lua_func(func_name, rule), file=generated_lua)
            
            for func_name, rule in additional_rules.items():
                print(get_lua_func(func_name, parse_rule(rule)), file=generated_lua)


    def create_connection_json():
        with open(output_connection_json, "w") as connection_json:
            output_json = [{"name": "Connections", "children":[]}]
            children = output_json[0]["children"]

            for node_name, node in data["nodes"].items():
                func_name = get_function_name(node_name)

                if func_name == None:
                    continue

                if func_name in nodes_aliases or func_name in region_aliases:
                    children.append({
                        "name": func_name,
                        "access_rules": [f"^${func_name}"]
                    })
                elif node_name in reverse_nodes:
                    access_rules = [f"^${func_name}"]
                    if any([reverse_nodes[node_name] == item.clientKey for _, item in starts.items()]):
                        access_rules.append(f"$isSpawn|{reverse_nodes[node_name]}")

                    children.append({
                        "name": reverse_nodes[node_name],
                        "access_rules": access_rules
                    })

            for func_name, _ in additional_rules.items():
                children.append({
                    "name": func_name,
                    "access_rules": [f"^${func_name}"]
                })
            
            json.dump(output_json, connection_json, indent=4)


    def update_connection_json():
        def add_entry_IF(lst, entry_name):
            for entry in lst:
                if entry["name"] == entry_name:
                    return entry
            
            lst.append({
                "name": entry_name,
                "children": []
            })
            return lst[-1]

        connections_accesses = {}
        with open(output_connection_json, "r") as connection_json:
            f_content = json.load(connection_json)
            for entry in f_content[0]["children"]:
                connections_accesses[entry["name"]] = entry["access_rules"]

        json_output = []

        for c_name, c_access in connections_accesses.items():
            if c_name in missing_paths:
                splitted_name = missing_paths[c_name]
            else:
                splitted_name = re.split(r"(\d+)", c_access[0][2:], 1)
                if c_name not in region_aliases:
                    splitted_name[2] = c_name
            
            output_entry = add_entry_IF(json_output, splitted_name[0])
            output_entry = add_entry_IF(output_entry["children"], splitted_name[1])
            output_entry["children"].append({
                "name": splitted_name[2],
                "access_rules": c_access
            })

        with open(output_connection_json, "w") as connection_json:
            json.dump(json_output, connection_json, indent=4)


    def update_location_jsons():
        for json_file_name in os.listdir(locations_folder_path):
            print(f"Starting to convert {json_file_name}...")
            full_path = f"{locations_folder_path}/{json_file_name}"
            f_content = []
            with open(full_path, "r") as json_file:
                f_content = json.load(json_file)

            f_locations = f_content[0]["children"]

            for loc in f_locations:
                has_glitched_logic = False
                if "access_rules" in loc:
                    for rule in loc["access_rules"]:
                        if '[' in rule:
                            has_glitched_logic = True
                    
                    if not has_glitched_logic:
                        del loc["access_rules"]
                
                for section in loc["sections"]:
                    func_name = get_associated_func(f_content[0]["name"], loc["name"], section["name"])

                    if "access_rules" in section:
                        section["access_rules"] = list(filter(lambda r : "[" in r, section["access_rules"]))
                        section["access_rules"].insert(0, func_name)
                    else:
                        section["access_rules"] = [ func_name ]

            with open(full_path, "w") as json_file:
                json.dump(f_content, json_file, indent=4)
            
            print(f"Conversion done !")


    def add_nodes_path_to_properties():
        with open(output_connection_json, "r") as connection_json:
            f_content = json.load(connection_json)
        
        loc_path = {}
        for map in f_content:
            for sub_map in map["children"]:
                for location in sub_map["children"]:
                    combined_name = f'{map["name"]}{sub_map["name"]}{location["name"]}'
                    loc_name = combined_name if combined_name in region_aliases else location["name"]
                    loc_path[loc_name] = f'@{map["name"]}/{sub_map["name"]}/{location["name"]}'
        
        with open(poptracker_json_path, "r") as properties_json:
            pop_data = json.load(properties_json)
        
        pop_data["nodes_connection_path"] = loc_path

        with open(poptracker_json_path, "w") as properties_json:
            json.dump(pop_data, properties_json, indent=2)


    
    ######################## GENERATORS CALLS ########################
    
    # Uncomment to generate lua logic file
    create_generated_lua()

    # Uncomment to generate connection json for poptracker ---- OUTDATED
    # create_connection_json()

    # Uncomment to update connections
    # update_connection_json()

    # Uncomment to update location jsons
    # update_location_jsons()

    # add_nodes_path_to_properties()
