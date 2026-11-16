import datetime
import signal
import threading
from collections.abc import Callable

import click
from flask import Blueprint, current_app

from flightlog.application.worker import process_one_job

bp = Blueprint("worker", __name__, cli_group=None)


def register_signals(stop: threading.Event) -> None:
    """Turn Ctrl+C and SIGTERM (docker compose stop) into a stop between jobs."""

    def handle(signum, frame):
        print(f"Received signal {signum}, shutting down gracefully...")
        stop.set()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)


@bp.cli.command("worker")
@click.option(
    "--once", is_flag=True, help="Stop when the queue is empty (for tests and CI).", default=False
)
@click.option("--poll-interval", default=1.0, show_default=True, help="Seconds to wait when idle.")
def worker(once: bool, poll_interval: float) -> None:
    """Process queued jobs until stopped. Ctrl+C or SIGTERM stop after the current job."""
    stop = threading.Event()
    if not once:
        register_signals(stop)

    new_unit_of_work = current_app.extensions["worker_unit_of_work"]

    def process() -> bool:
        return process_one_job(new_unit_of_work, datetime.datetime.now(datetime.UTC))

    run(once, poll_interval, stop, process)


def run(
    once: bool, poll_interval: float, stop: threading.Event, process: Callable[[], bool]
) -> None:
    """Process jobs until stopped. When idle, wait (a stop wakes it) or, with once, end."""
    while not stop.is_set():
        if not process():
            if once:
                break
            stop.wait(poll_interval)
