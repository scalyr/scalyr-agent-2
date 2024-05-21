import time
import sys


def message(stream):
    return f"{stream}_BEGIN_LONG_MESSAGE {'X' * 8192} {stream}_END_LONG_MESSAGE"


if __name__ == "__main__":
    while True:
        print(message("stdout"))
        print(message("stderr"), file=sys.stderr)
        time.sleep(1)
