import sys


def custom_any(iterable):
    if sys.version_info[:2] > (2, 4):
        return any(iterable)
    else:
        for element in iterable:
            if element:
                return True
        return False


def custom_all(iterable):
    if sys.version_info[:2] > (2, 4):
        return all(iterable)
    else:
        for element in iterable:
            if not element:
                return False
        return True


def custom_defaultdict(default_type):
    if sys.version_info[:2] > (2, 4):
        from collections import defaultdict
        return defaultdict(default_type)
    else:
        class DefaultDict(dict):
            def __getitem__(self, key):
                if key not in self:
                    dict.__setitem__(self, key, default_type())
                return dict.__getitem__(self, key)
        return DefaultDict()
