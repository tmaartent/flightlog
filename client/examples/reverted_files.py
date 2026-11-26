"""Which files led to a reverted pull request most often? Prints only `count path` lines.

    FLIGHTLOG_URL=http://localhost:8000 FLIGHTLOG_API_KEY=fl_… \\
        python client/examples/reverted_files.py --repo shop --since 2026-11-01

Every session of the repo goes through this script; only the answer reaches whoever (or
whatever agent) runs it. That's what the client is for (ADR-0020).
"""

import argparse
import datetime
from collections import Counter

from flightlog_client import Flightlog, Outcome


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--since", type=datetime.date.fromisoformat, required=True)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    reverted: Counter[str] = Counter()
    for session in Flightlog().summaries(args.repo, since=args.since):
        pr = session.pull_request
        if pr and pr.outcome is Outcome.REVERTED and session.summary:
            reverted.update(session.summary.files_touched)

    # most_common breaks ties by first appearance; sort by count, then path, for stable output.
    for path, count in sorted(reverted.items(), key=lambda item: (-item[1], item[0]))[: args.top]:
        print(f"{count} {path}")


if __name__ == "__main__":
    main()
