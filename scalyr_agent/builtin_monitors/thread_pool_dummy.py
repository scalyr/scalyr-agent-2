from six.moves.socketserver import ThreadingMixIn


class QueueMixin(ThreadingMixIn):
    def __init__(self, global_config):
        pass
