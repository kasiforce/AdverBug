"""Filter JavaScript P50 candidates that are clearly non-project repositories."""
import argparse,csv,re
RULES=[("tutorial_or_course",re.compile(r"\b(tutorials?|courses?|courseware|workshop|lecture|learning|guide|beginner)\b|教程|课程|学习|入门",re.I)),("book_or_documentation",re.compile(r"\b(book|textbook|cookbook|documentation|docs?)\b|\b(论文|教材|书籍)\b",re.I)),("examples_or_samples",re.compile(r"\b(example|examples|sample|samples|demo|showcase|playground|boilerplate|template)\b",re.I)),("exercise_collection",re.compile(r"\b(leetcode|algorithm collection|coding challenges?|interview questions?|exercises?|kata|cheatsheet|style guide)\b",re.I))]
NAME_TOKENS={"tutorial","tutorials","examples","example","samples","sample","learning","leetcode","playground","cookbook","boilerplate","templates"}
def classify(row):
 tokens={x for x in re.split(r"[^a-z0-9]+",row.get("full_name","").lower()) if x}; text=f"{row.get('full_name','')} {row.get('description','') or ''}"
 for label,pattern in RULES:
  if tokens & NAME_TOKENS and label in {"tutorial_or_course","examples_or_samples","exercise_collection"}:return label
  if pattern.search(text):
   if label=="examples_or_samples" and not(tokens & {"examples","example","samples","sample"}) and not re.search(r"\b(collection|set of|repository of)\b",text,re.I):continue
   return label
 return ""
def main():
 p=argparse.ArgumentParser();p.add_argument("--input",default="AdverBug/github_repos_javascript_p50.csv");p.add_argument("--output",default="AdverBug/github_repos_javascript_projects.csv");p.add_argument("--excluded-output",default="AdverBug/github_repos_javascript_nonproject_excluded.csv");a=p.parse_args()
 with open(a.input,newline="",encoding="utf-8") as f:rows=list(csv.DictReader(f))
 fields=list(rows[0])+["nonproject_filter_reason"] if rows else ["nonproject_filter_reason"];kept=[];excluded=[]
 for row in rows:
  row=dict(row);row["nonproject_filter_reason"]=classify(row);(excluded if row["nonproject_filter_reason"] else kept).append(row)
 for path,data in ((a.output,kept),(a.excluded_output,excluded)):
  with open(path,"w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
 print(f"total={len(rows)} kept={len(kept)} excluded={len(excluded)}")
 for row in excluded:print(f"EXCLUDE {row['full_name']} [{row['nonproject_filter_reason']}]")
if __name__=="__main__":main()
