"""Convert internal AI review comments into GitHub Review API payload."""

from .schemas import ReviewComment


class GitHubCommentMapper:

    @staticmethod
    def to_github(comments: list[ReviewComment]) -> list[dict]:
        github_comments = []

        for comment in comments:
            github_comments.append(
                {
                    "path": comment.file,
                    "line": comment.line,
                    "side": "RIGHT",
                    "body": (
                        f"### {comment.severity.upper()} · {comment.category}\n\n"
                        f"{comment.message}\n\n"
                        f"**Suggested fix**\n{comment.suggestion}\n\n"
                        f"Confidence: {comment.confidence:.2f}"
                    ),
                }
            )

        return github_comments