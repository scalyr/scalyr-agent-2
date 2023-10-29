import threading
from concurrent.futures import Executor, ThreadPoolExecutor

from scalyr_agent import scalyr_logging

global_log = scalyr_logging.getLogger(__name__)

class ExecutorMixIn:
    def __init__(self):
        # Using 4 threads for processing requests, because of GIL and CPU bound tasks higher number would not help process the data faster.
        self._request_processing_executor = ThreadPoolExecutorFactory.get_singleton("request_processing_executor", max_workers=4)
        self._request_reading_executor = ThreadPoolExecutorFactory.get_singleton("request_reading_executor")

    def process_request_thread(self, request, client_address):
        """Same as in BaseServer but as a thread.

        In addition, exception handling is done here.

        """
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def process_request(self, request, client_address):
        if not self._request_processing_executor:
           raise ValueError(str(self.__class__) + " is not initialized properly")

        """Start a new thread to process the request."""
        self._request_reading_executor.submit(
            self.process_request_thread, request, client_address
        )

    def server_close(self):
        super().server_close()

class ThreadPoolExecutorFactory():
    __lock = threading.Lock()
    __instances = {}

    @classmethod
    def get_singleton(cls, name, max_workers=None):
        if name not in cls.__instances:
            with cls.__lock:
                if name not in cls.__instances:
                    cls.__instances[name] = ThreadPoolExecutor(max_workers=max_workers)
        return cls.__instances[name]

    @classmethod
    def shutdown(cls, wait=True, *, cancel_futures=False):
        wait_on_futures_str = " and waiting on futures" if wait else ""
        for name, executor in cls.__instances.items():
            global_log.info("Shutting down ThreadPoolExecutor%s: %s", wait_on_futures_str, name)
            try:
                executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            except Exception as e:
                global_log.error("Failed shutting down the ThreadPoolExecutor %s", executor, exc_info=e)
