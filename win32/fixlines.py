import sys
from os import path

def line_generator(filename):
    assert path.isfile(filename), "{} does not exist".format(filename)
    with open(filename, 'r') as fp:
        for line in fp:
            yield line.replace('\n', '\r\n')
        

if __name__ == "__main__":
    try:
        lines = line_generator(sys.argv[1])
        for line in lines:
            sys.stdout.write(line)
    except IndexError:
        sys.stderr.write("Missing required argument\n")
        sys.stderr.write("USAGE: {} [FILE]\n".format(path.basename(sys.argv[0])))
