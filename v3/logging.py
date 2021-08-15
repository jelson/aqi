#!/usr/bin/env python3

import sys

logfile = sys.stdout

def say(s):
    logfile.write(f"{s}\n")

def open_logfile(filename):
    global logfile
    logfile = open(filename, "a")
