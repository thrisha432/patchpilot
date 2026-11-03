from app.webhook import GitHubPush, parse_push


def test_field_names_also_accepted():
    push = GitHubPush(ref="r", head_commit_id="x", repo_name="y")
    assert push.head_commit_id == "x"


def test_forced():
    assert parse_push({"ref": "r", "after": "a", "repository": "b", "forced": True}).forced
