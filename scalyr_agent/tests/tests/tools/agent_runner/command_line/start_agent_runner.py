from .. import DirectAgentRunner


def start():
    runner = DirectAgentRunner(fork=False)
    runner.start()


if __name__ == '__main__':
    start()
