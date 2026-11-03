from pydantic import BaseModel, ConfigDict, Field


class GitHubPush(BaseModel):
    ref: str
    head_commit_id: str = Field(alias="after")
    repo_name: str = Field(alias="repository")
    forced: bool = False

    model_config = ConfigDict(populate_by_name=True)


def parse_push(payload: dict) -> GitHubPush:
    return GitHubPush.model_validate(payload)
