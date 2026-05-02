"""
Diff-streamer contract.

Token saving:
- The assistant response is constrained to patches, which avoids restating
  complete files after VibeFlow already supplied compact context.
"""

DIFF_ONLY_INSTRUCTION = """\
Return changes only as a unified git diff.
Do not include full-file rewrites unless the whole file is genuinely new.
Use paths relative to the project root.
"""


def diff_contract() -> dict[str, str]:
    return {
        "format": "git_diff",
        "instruction": DIFF_ONLY_INSTRUCTION,
    }
