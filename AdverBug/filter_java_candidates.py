"""Filter Java P50 candidates that are clearly non-project repositories."""
import argparse, csv, re
from pathlib import Path

RULES = [
    ("tutorial_or_course", re.compile(r"\b(tutorials?|courseware|course|workshop|lecture|learning|beginner|getting started)\b|教程|课程|学习|入门", re.I)),
    ("book_or_documentation", re.compile(r"\b(book|textbook|cookbook|documentation|docs?)\b|\b(论文|教材|书籍)\b", re.I)),
    ("examples_or_samples", re.compile(r"\b(example|examples|sample|samples|demo|showcase)\b", re.I)),
    ("exercise_collection", re.compile(r"\b(leetcode|algorithm collection|coding challenges?|interview questions?|exercises?|kata|practice problems?)\b", re.I)),
]
NAME_TOKENS = {"tutorials", "tutorial", "examples", "example", "samples", "sample", "learning", "leetcode", "playground", "cookbook"}

def classify(row):
    name_tokens = {token for token in re.split(r"[^a-z0-9]+", row.get("full_name", "").lower()) if token}
    text = f"{row.get('full_name','')} {row.get('description','') or ''}"
    for label, pattern in RULES:
        if name_tokens & NAME_TOKENS and label in {"tutorial_or_course", "examples_or_samples", "exercise_collection"}:
            return label
        if pattern.search(text):
            # Generic example/sample words in a production description are
            # weaker; require a repository-name token or collection language.
            if label == "examples_or_samples" and not (name_tokens & {"examples", "example", "samples", "sample"}) and not re.search(r"\b(collection|set of|repository of)\b", text, re.I):
                continue
            return label
    return ""

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--input", default="AdverBug/github_repos_java_p50.csv"); parser.add_argument("--output", default="AdverBug/github_repos_java_projects.csv"); parser.add_argument("--excluded-output", default="AdverBug/github_repos_java_nonproject_excluded.csv"); args=parser.parse_args()
    with open(args.input, newline="", encoding="utf-8") as f: rows=list(csv.DictReader(f))
    fields=list(rows[0]) + ["nonproject_filter_reason"] if rows else ["nonproject_filter_reason"]; kept=[]; excluded=[]
    for row in rows:
        reason=classify(row); row=dict(row); row["nonproject_filter_reason"]=reason
        (excluded if reason else kept).append(row)
    for path, data in ((args.output, kept), (args.excluded_output, excluded)):
        with open(path, "w", newline="", encoding="utf-8") as f: writer=csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(data)
    print(f"total={len(rows)} kept={len(kept)} excluded={len(excluded)}")
    for row in excluded: print(f"EXCLUDE {row['full_name']} [{row['nonproject_filter_reason']}]")

if __name__ == "__main__": main()
