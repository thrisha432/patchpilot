from app.webhook import parse_push


def test_aliases():
    push = parse_push({"ref": "refs/heads/main", "after": "abc123", "repository": "relay"})
    assert (push.head_commit_id, push.repo_name, push.forced) == ("abc123", "relay", False)
