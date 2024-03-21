from six.moves.socketserver import ThreadingMixIn

class ExecutorMixIn(ThreadingMixIn):
    def __init__(self, global_config):
        pass
