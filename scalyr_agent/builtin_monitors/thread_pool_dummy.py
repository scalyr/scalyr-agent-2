from socketserver import ThreadingMixIn


class ExecutorMixIn(ThreadingMixIn):
    def __init__(self):
        self._request_reading_executor = None
        self._request_processing_executor = None

class ThreadPoolExecutorFactory():
    @classmethod
    def shutdown(cls, wait=True, cancel_futures=False):
        pass
