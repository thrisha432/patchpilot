from pydantic import BaseModel


class GitHubPush(BaseModel):
    ref: str
    head_commit_id: str
    repo_name: str
    forced: bool = False

    class Config:
        fields = {
            "head_commit_id": {"alias": "after"},
            "repo_name": {"alias": "repository"},
        }
        allow_population_by_field_name = True


def parse_push(payload: dict) -> GitHubPush:
    return GitHubPush.parse_obj(payload)
