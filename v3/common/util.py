
# general utilities

import argparse


def gtzero(arg):
    arg = int(arg)
    if arg <= 0:
        raise argparse.ArgumentTypeError("argument must be > 0")
    return arg
