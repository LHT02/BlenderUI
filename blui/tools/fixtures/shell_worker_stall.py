"""Fault injection: emulate a stuck third-party shell extension."""
import sys
import time
sys.stdin.readline()
time.sleep(60)
