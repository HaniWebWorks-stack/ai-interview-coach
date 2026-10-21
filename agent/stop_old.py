"""Closes leftover copies of the coach agent and the viewer server from
earlier test runs (they keep running if a window is left open or hidden,
and would answer instead of the newest code). Only touches this project."""

import os
import time

import psutil

TARGETS = ("agent.py", "viewer_server.py")


def main() -> None:
    me = os.getpid()
    found = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info["pid"] == me:
                continue
            cmd = " ".join(p.info["cmdline"] or []).lower()
            if not any(t in cmd for t in TARGETS):
                continue
            where = cmd
            try:
                where += " " + p.cwd().lower()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
            if "ai-interview-coach" not in where:
                continue
            for child in p.children(recursive=True):
                child.terminate()
            p.terminate()
            found.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if found:
        psutil.wait_procs(found, timeout=5)
        time.sleep(1)
    print(f"Closed {len(found)} leftover copy/copies from earlier tests.")


if __name__ == "__main__":
    main()
