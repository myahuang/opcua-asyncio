from enum import Enum
from datetime import datetime
import uuid
from enum import IntEnum
import logging
import re

from asyncua import ua


logger = logging.getLogger(__name__)

def clean_name(name):
    """
    Remove characters that might be present in  OPC UA structures
    but cannot be part of of Python class names
    """
    name = re.sub(r'\W+', '_', name)
    name = re.sub(r'^[0-9]+', r'_\g<0>', name)

    return name



def get_default_value(uatype, enums=None):
    if enums is None:
        enums = {}
    if uatype == "String":
        return "None"
    elif uatype == "Guid":
        return "uuid.uuid4()"
    elif uatype in ("ByteString", "CharArray", "Char"):
        return b''
    elif uatype == "Boolean":
        return "True"
    elif uatype == "DateTime":
        return "datetime.utcnow()"
    elif uatype in ("Int16", "Int32", "Int64", "UInt16", "UInt32", "UInt64", "Double", "Float", "Byte", "SByte"):
        return 0
    elif uatype in enums:
        return f"ua.{uatype}({enums[uatype]})"
    elif hasattr(ua, uatype) and issubclass(getattr(ua, uatype), Enum):
        # We have an enum, try to initilize it correctly
        val = list(getattr(ua, uatype).__members__)[0]
        return f"ua.{uatype}.{val}"
    else:
        return f"ua.{uatype}()"


async def make_structure_code(data_type_node):
    """
    given a StructureDefinition object, generate Python code
    """
    sdef = await data_type_node.read_data_type_definition()
    name = clean_name((await data_type_node.read_browse_name()).Name)
    if sdef.StructureType != ua.StructureType.Structure:
        raise NotImplementedError("Only StructureType implemented")

    code = f"""

class {name}:

    '''
    {name} structure autogenerated from StructureDefinition object
    '''

"""
    code += '    ua_types = [\n'
    uatypes = []
    for field in sdef.Fields:
        prefix = 'ListOf' if field.ValueRank >= 1 else ''
        if field.DataType.Identifier not in ua.ObjectIdNames:
            raise RuntimeError(f"Unknown  field datatype for field: {field} in structure:{sdef.Name}")
        uatype = prefix + ua.ObjectIdNames[field.DataType.Identifier]
        if uatype == 'ListOfChar':
            uatype = 'String'
        uatypes.append((field, uatype))
        code += f"        ('{field.Name}', '{uatype}'),\n"
    code += "    ]"
    code += """
    def __str__(self):
        vals = [name + ": " + str(val) for name, val in self.__dict__.items()]
        return self.__class__.__name__ + "(" + ", ".join(vals) + ")"

    __repr__ = __str__

    def __init__(self):
"""
    if not sdef.Fields:
        code += "      pass"
    for field, uatype in uatypes:
        default_value = get_default_value(uatype)
        code += f"        self.{field.Name} = {default_value}\n"
    return code


async def _generate_object(data_type_node, env=None, enum=False):
    """
    generate Python code and execute in a new environment
    return a dict of structures {name: class}
    Rmw: Since the code is generated on the fly, in case of error the stack trace is
    not available and debugging is very hard...
    """
    if env is None:
        env = {}
    #  Add the required libraries to dict
    if "ua" not in env:
        env['ua'] = ua
    if "datetime" not in env:
        env['datetime'] = datetime
    if "uuid" not in env:
        env['uuid'] = uuid
    if "enum" not in env:
        env['IntEnum'] = IntEnum
    # generate classe add it to env dict
    if enum:
        code = await make_enum_code(data_type_node)
    else:
        code = await make_structure_code(data_type_node)
    logger.debug("Executing code: %s", code)
    exec(code, env)
    return env


async def load_data_type_definitions(server, base_node=None):
    if base_node is None:
        base_node = server.nodes.base_structure_type
    for desc in await base_node.get_children_descriptions(refs=ua.ObjectIds.HasSubtype):
        if desc.BrowseName.Name == "FilterOperand":
            #FIXME: find out why that one is not in ua namespace...
            continue
        if hasattr(ua, desc.BrowseName.Name):
            continue
        logger.warning("Registring structure %s %s", desc.NodeId, desc.BrowseName)
        node = server.get_node(desc.NodeId)
        await _generate_object(node)


async def make_enum_code(data_type_node):
    """
    if node has a DataTypeDefinition arttribute, generate enum code
    """
    edef = await data_type_node.read_data_type_definition()
    name = clean_name((await data_type_node.read_browse_name()).Name)
    code = f"""

class {name}(IntEnum):

    '''
    {name} EnumInt autogenerated from xml
    '''

"""

    for field in edef.Fields:
        name = field.Name
        value = field.Value
        code += f"    {name} = {value}\n"

    return code



async def load_enums(server, base_node=None):
    if base_node is None:
        base_node = server.nodes.enum_data_type
    for desc in await base_node.get_children_descriptions(refs=ua.ObjectIds.HasSubtype):
        if hasattr(ua, desc.BrowseName.Name):
            continue
        logger.warning("Registring Enum %s %s", desc.NodeId, desc.BrowseName)
        node = server.get_node(desc.NodeId)
        await _generate_object(node)


