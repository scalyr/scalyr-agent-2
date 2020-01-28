from lib2to3.fixer_base import BaseFix
from lib2to3.pgen2 import token
from lib2to3.fixer_util import Name, Node, Leaf, LParen, RParen, Dot, Newline
import libmodernize


class FixStructUnicode(BaseFix):
    """
        This fixer searches for places where we calling struct.pack or struct.unpack,
        and replaces them with 'scalyr_agent.compat.struct_pack' or struct_unpack.
        This is needed because struct library does not allow unicode format strings.
        """
    BM_compatible = True
    PATTERN = """
            power< head='struct' trailer< dot='.' method=('pack'|'unpack') > args=any+>
       """

    def transform(self, node, results):
        libmodernize.touch_import('scalyr_agent', 'compat', node)
        head = results["head"]
        method = results["method"][0]
        head.value = "compat"
        method.value = 'struct_{}_unicode'.format(method.value)

        node.changed()


