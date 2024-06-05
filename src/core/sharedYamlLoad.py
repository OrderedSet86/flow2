from pathlib import Path
from typing import Union

import yaml


cached_yaml_loads = {}


def loadYamlFile(yaml_path: Union[str, Path]) -> dict:
    yaml_path_str = str(yaml_path)

    if yaml_path_str in cached_yaml_loads:
        return cached_yaml_loads[yaml_path_str]

    else:
        with open(yaml_path, 'r') as f:
            conf = yaml.safe_load(f)
        cached_yaml_loads[yaml_path_str] = conf
        return conf