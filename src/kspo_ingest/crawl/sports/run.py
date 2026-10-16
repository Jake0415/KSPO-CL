"""CLI runner for the sports.re.kr crawler.

    python -m kspo_ingest.crawl.sports.run --mode full --max-pages 2 --db /tmp/x.db
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from .engine import Config, Engine
from .seeds import load_seeds
from .store import Store


async def _run_with_signals(engine, mode):
    """Run the engine, converting SIGTERM/SIGINT into task cancellation so the
    engine's `finally` writes a terminal run status instead of leaving a ghost
    'running' row (audit 2026-07-08)."""
    import contextlib
    import signal

    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(engine.run(mode))
    for sig in (signal.SIGTERM, signal.SIGINT):
        # non-main thread / platform without signal support → best-effort
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, task.cancel)
    try:
        return await task
    except asyncio.CancelledError:
        return engine.stats


def main():
    ap = argparse.ArgumentParser(description="sports.re.kr crawler")
    ap.add_argument("--mode", choices=["full", "incremental"], default="full")
    ap.add_argument("--db", default="sports_crawl.db")
    ap.add_argument("--max-pages", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--min-delay", type=float, default=0.35)
    ap.add_argument("--only", default=None,
                    help="restrict to source_type (board,research,static,bid,voc,pub)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    store = Store(args.db)
    load_seeds(store)
    if args.only:
        store.db.execute("UPDATE crawl_source SET enabled=0 WHERE source_type!=?",
                         (args.only,))
        store.db.commit()

    cfg = Config(db_path=args.db, max_pages=args.max_pages,
                 concurrency=args.concurrency, min_delay=args.min_delay,
                 incremental=(args.mode == "incremental"))
    engine = Engine(cfg, store)
    stats = asyncio.run(_run_with_signals(engine, args.mode))

    print("=== RUN STATS ===")
    print(json.dumps(stats.as_dict(), indent=2, ensure_ascii=False))
    print("=== DB COUNTS ===")
    print(json.dumps(store.counts(), indent=2, ensure_ascii=False))
    store.close()


if __name__ == "__main__":
    main()
