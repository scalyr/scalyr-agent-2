from six.moves.socketserver import ThreadingMixIn

class ExecutorMixIn(ThreadingMixIn):
    def __init__(self, global_config):
        self._request_reading_executor = None
        self._request_processing_executor = None

class ThreadPoolExecutorFactory():
    @classmethod
    def shutdown(cls, wait=True):
        pass
