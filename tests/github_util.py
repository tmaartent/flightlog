import datetime

T0 = datetime.datetime(2026, 11, 16, 10, 0, tzinfo=datetime.UTC)


def pull_request_payload(
    number: int = 7,
    branch: str = "feat/x",
    title: str = "Add x",
    state: str = "open",
    merged_at: datetime.datetime | None = None,
    updated_at: datetime.datetime = T0,
    body: str | None = None,
    repo: str = "flightlog",
    action: str = "opened",
) -> dict:
    """The fields of a GitHub `pull_request` delivery that Flightlog reads, and a few more."""
    return {
        "action": action,
        "number": number,
        "pull_request": {
            "number": number,
            "title": title,
            "body": body,
            "state": state,
            "merged": merged_at is not None,
            "merged_at": merged_at.isoformat().replace("+00:00", "Z") if merged_at else None,
            "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
            "head": {"ref": branch, "sha": "0cb1b1c"},
            "base": {"ref": "main"},
        },
        "repository": {"name": repo, "full_name": f"tmaartent/{repo}"},
    }
