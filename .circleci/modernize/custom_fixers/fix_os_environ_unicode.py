from lib2to3.fixer_base import BaseFix
from lib2to3.pgen2 import token
import libmodernize


class FixOsEnvironUnicode(BaseFix):
    """
    This fixer searches for places where we fetch data from os.environ,
    for example: 'os.environ["1"]', 'os.environ.get', 'os.environ.items()'
    and replaces them with 'scalyr_agent.compat.environ_unicode'.
    This is needed because environ returns 'str' in python2 and we need unicode.
    """

    BM_compatible = True
    PATTERN = """
                power< head='os' trailer< dot='.' method='environ' > any* >
    """

    def transform(self, node, results):
        next_sibling = node.next_sibling
        if (
            next_sibling
            and next_sibling.type == token.EQUAL
            and next_sibling.value == "="
        ):
            return
        prev_sibling = node.prev_sibling
        if prev_sibling and prev_sibling.type == token.NAME:
            if prev_sibling.value in ("del", "in"):
                return
        method = results["method"]
        method_node = method.parent
        if str(method_node.next_sibling) in (".clear", ".update"):
            return
        libmodernize.touch_import("scalyr_agent", "compat", node)
        head = results["head"]
        head.value = head.value.replace("os", "compat")
        method.value = "os_environ_unicode"
        node.changed()
