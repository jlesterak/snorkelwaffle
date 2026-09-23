"""Entry point: ``python -m snorkelwaffle [serve | compare FILE FILE...]``."""

import argparse
import logging
import os
import signal
import sys

from . import __version__, config, fingerprint, matcher
from .abs_client import AbsClient
from .db import Database
from .engine import Engine, fmt_time
from .web import App, serve
from .worker import RingLog, Worker


def setup_logging(level):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    ring = RingLog()
    ring.setFormatter(logging.Formatter("%(message)s"))
    ring.setLevel(logging.INFO)
    root.addHandler(ring)
    return ring


def cmd_serve(env):
    ring = setup_logging(env.log_level)
    log = logging.getLogger("snorkelwaffle")
    log.info("snorkelwaffle %s starting; libraries: %s", __version__, ", ".join(env.library_dirs))
    db = Database(os.path.join(env.data_dir, "snorkelwaffle.db"))
    engine = Engine(db, env)
    abs_client = AbsClient(env.abs_url, env.abs_token, env.abs_library_id)
    worker = Worker(engine, db, abs_client)
    server = serve(App(db, engine, worker, abs_client, env, ring), env.host, env.port)

    def shutdown(*_):
        log.info("Shutting down")
        worker.stop()
        server.shutdown()

    signal.signal(signal.SIGTERM, lambda *a: __import__("threading").Thread(target=shutdown).start())
    worker.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown()


def cmd_compare(files):
    """Print audio shared between two or more files (quick manual check, no database)."""
    fps = {f: fingerprint.fingerprint_file(f, nice=0) for f in files}
    names = list(fps)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for m in matcher.find_matches(fps[a], fps[b]):
                sa, ea = fingerprint.items_to_span(m.a_start, m.a_end)
                sb, eb = fingerprint.items_to_span(m.b_start, m.b_end)
                print(f"{os.path.basename(a)} {fmt_time(sa)}-{fmt_time(ea)}  ==  "
                      f"{os.path.basename(b)} {fmt_time(sb)}-{fmt_time(eb)}  ({ea - sa:.1f}s, ber {m.ber:.2f})")


def main():
    p = argparse.ArgumentParser(prog="snorkelwaffle", description=__doc__)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the web UI and background worker (default)")
    c = sub.add_parser("compare", help="show audio shared between files")
    c.add_argument("files", nargs="+")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args()
    if args.cmd == "compare":
        if len(args.files) < 2:
            p.error("compare needs at least two files")
        cmd_compare(args.files)
    else:
        cmd_serve(config.Env.load())


if __name__ == "__main__":
    main()
