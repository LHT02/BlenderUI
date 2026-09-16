"""Fault injection: emulate a native extension terminating its host."""
import os
import sys
sys.stdin.readline()
os._exit(71)
