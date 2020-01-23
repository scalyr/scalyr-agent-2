from lib2to3.fixer_base import BaseFix
import libmodernize


class FixOsGetenvUnicode(BaseFix):
    """
        This fixer searches for places where we calling os.getenv,
        and replaces them with 'scalyr_agent.compat.os_getenv_unicode'.
        This is needed because os.getenv returns 'str' in python2 and we need unicode.
        """
    BM_compatible = True
    PATTERN = """
                power<head='os' trailer< dot='.' method='getenv' > any* >
    """

    def transform(self, node, results):
        libmodernize.touch_import("scalyr_agent", "compat", node)
        method = results['method']
        head = results["head"]
        head.value = head.value.replace("os", "compat")
        method.value = "os_getenv_unicode"
        node.changed()


