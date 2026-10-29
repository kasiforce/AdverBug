"""Calculate Java production-source metrics and apply P50 filtering."""
from __future__ import annotations
import argparse, csv, os, shutil, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median
from pathlib import Path

EXCLUDED_DIRS={".git",".gradle",".idea","target","build","out","bin","generated","generated-sources","generated-test-sources","docs","doc","documentation","examples","example","samples","sample","benchmarks","benchmark","perf","performance","fixtures","fixture","test","tests","testing","testfixtures","integration-test","integration-tests","integrationtest","it","src-test","androidtest"}

def run(cmd,cwd=None,timeout=600): return subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout,check=False)

def is_production_java(rel_path):
    p=rel_path.replace(os.sep,"/").split("/"); low=[x.lower() for x in p]; base=low[-1]
    if not base.endswith(".java") or not any(low[i:i+3]==["src","main","java"] for i in range(max(0,len(low)-2))): return False
    if any(x in EXCLUDED_DIRS for x in low[:-1]) or base in {"package-info.java","module-info.java"}: return False
    return not base.endswith(("test.java","tests.java","testcase.java","it.java","itcase.java","integrationtest.java","spec.java"))

def count_java_loc(path):
    n=0; block=False; quote=None; escaped=False; text_block=False; handle=path if hasattr(path,"read") else open(path,encoding="utf-8",errors="ignore")
    try:
        for line in handle:
            code=False; i=0
            while i<len(line):
                c=line[i]; nxt=line[i+1] if i+1<len(line) else ""
                if block:
                    if c=="*" and nxt=="/": block=False; i+=2; continue
                    i+=1; continue
                if text_block:
                    if line.startswith('"""',i) and not escaped: text_block=False; i+=3; continue
                    i+=1; continue
                if quote:
                    code=True
                    if escaped: escaped=False
                    elif c=="\\": escaped=True
                    elif c==quote: quote=None
                    i+=1; continue
                if line.startswith('"""',i): code=True; text_block=True; i+=3; continue
                if c in ('"',"'"): code=True; quote=c; escaped=False; i+=1; continue
                if c=="/" and nxt=="/": break
                if c=="/" and nxt=="*": block=True; i+=2; continue
                if not c.isspace(): code=True
                i+=1
            if code: n+=1
    finally:
        if handle is not path: handle.close()
    return n

def clone_measure(repo,root):
    full=repo["full_name"]; target=root/full.replace("/","__"); url=f"https://github.com/{full}.git"
    try:
        proc=run(["git","clone","--quiet","--depth=1","--filter=blob:none","--no-checkout",url,str(target)])
        if proc.returncode!=0:
            shutil.rmtree(target,ignore_errors=True); proc=run(["git","clone","--quiet","--depth=1","--no-checkout",url,str(target)])
        if proc.returncode!=0: return repo,{"metric_status":"clone_failed","metric_error":proc.stderr[-500:]}
        for cmd in (["git","sparse-checkout","init","--no-cone"],["git","sparse-checkout","set","--no-cone","**/src/main/java/**/*.java","*/src/main/java/**/*.java"],["git","checkout","--quiet","HEAD"]):
            proc=run(cmd,cwd=target)
            if proc.returncode!=0: return repo,{"metric_status":"checkout_failed","metric_error":proc.stderr[-500:]}
        files=[]
        for base,dirs,names in os.walk(target):
            dirs[:]=[d for d in dirs if d.lower() not in EXCLUDED_DIRS]
            for name in names:
                rel=os.path.relpath(os.path.join(base,name),target)
                if is_production_java(rel): files.append(os.path.join(base,name))
        sha=run(["git","rev-parse","HEAD"],cwd=target).stdout.strip()
        if not files: return repo,{"metric_status":"no_source","metric_sha":sha}
        lengths=[count_java_loc(f) for f in files]; ordered=sorted(lengths)
        return repo,{"metric_status":"ok","metric_sha":sha,"source_file_count":len(lengths),"source_loc":sum(lengths),"avg_file_loc":sum(lengths)/len(lengths),"median_file_loc":median(lengths),"p90_file_loc":ordered[max(0,int(.9*len(ordered))-1)],"max_file_loc":max(lengths)}
    except (OSError,subprocess.TimeoutExpired) as exc: return repo,{"metric_status":f"error:{type(exc).__name__}"}
    finally: shutil.rmtree(target,ignore_errors=True)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input",default="AdverBug/github_repos_java.csv"); p.add_argument("--metrics-output",default="AdverBug/github_repos_java_metrics.csv"); p.add_argument("--filtered-output",default="AdverBug/github_repos_java_p50.csv"); p.add_argument("--workers",type=int,default=8); a=p.parse_args()
    with open(a.input,newline="",encoding="utf-8") as f: repos=list(csv.DictReader(f))
    root=Path(tempfile.mkdtemp(prefix="java-repo-metrics-")); results={}
    try:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures=[pool.submit(clone_measure,r,root) for r in repos]
            for i,future in enumerate(as_completed(futures),1):
                repo,m=future.result(); results[repo["full_name"]]=m; print(f"[{i}/{len(repos)}] {repo['full_name']}: {m.get('metric_status')}",flush=True)
    finally: shutil.rmtree(root,ignore_errors=True)
    good=[m for m in results.values() if m.get("metric_status")=="ok"]
    if not good: raise SystemExit("no successful Java metrics")
    thresholds={"source_file_count":median(m["source_file_count"] for m in good),"source_loc":median(m["source_loc"] for m in good),"median_file_loc":median(m["median_file_loc"] for m in good)}; print("P50 thresholds:",thresholds)
    fields=list(repos[0])+["metric_status","metric_sha","source_file_count","source_loc","avg_file_loc","median_file_loc","p90_file_loc","max_file_loc","p50_selected"]; rows=[]; selected=[]
    for repo in repos:
        m=results[repo["full_name"]]; row=dict(repo); row.update(m); row["p50_selected"]=m.get("metric_status")=="ok" and all(m[k]>=v for k,v in thresholds.items()); rows.append(row); selected.append(row) if row["p50_selected"] else None
    for out,data in ((a.metrics_output,rows),(a.filtered_output,selected)):
        with open(out,"w",newline="",encoding="utf-8") as f: w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(data)
    print(f"successful={len(good)} selected={len(selected)} total={len(repos)}")
if __name__=="__main__": main()
