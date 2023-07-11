import logging


def init_logging():
    logging.basicConfig(
        level=logging.INFO,
        format=f"[%(levelname)s][%(module)s:%(lineno)s] %(message)s",
    )