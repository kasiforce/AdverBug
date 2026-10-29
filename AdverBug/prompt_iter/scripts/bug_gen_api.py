"""Generate buggy code via the REAL LLM API, mirroring the pipeline contract:
- prompt rendered from the candidate prompt version (prompt_versions.py)
- temperature 0.7, max_tokens 16384
- JSON parsing identical to AdverBug/bug_generation_agent.py

Usage:
  /data/home/cjy/miniconda3/envs/software-testing/bin/python scripts/bug_gen_api.py \
      <data_path> <entry_idx> <out_dir> [version] [model] [endpoint] [api_key] [buggy_file] [testinfo_file]

Defaults: version=v2 (final), model=gpt-5-nano, endpoint=https://api.agicto.cn/v1,
key = $LLM_API_KEY. If BOTH buggy_file and testinfo_file are given, the enhance
prompt is used (attempt >= 2 in the pipeline).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from prompt_versions import VERSIONS  # noqa: E402
from openai import OpenAI  # noqa: E402


def parse_bug_json(raw):
    """Same tolerant parsing as bug_generation_agent.py."""
    b = raw.split("```json")[-1].split("```")[0].strip()
    if not b.startswith("{"):
        text = b.split("{")[0]
        b = b.split(text)[-1].strip()
    try:
        return json.loads(b)
    except Exception:
        s, e = raw.find("{"), raw.rfind("}")
        return json.loads(raw[s:e + 1])


def main():
    data_path = sys.argv[1]
    idx = int(sys.argv[2])
    out_dir = sys.argv[3]
    version = sys.argv[4] if len(sys.argv) > 4 else "v2"
    model = sys.argv[5] if len(sys.argv) > 5 else "gpt-5-nano"
    endpoint = sys.argv[6] if len(sys.argv) > 6 else "https://api.agicto.cn/v1"
    key = sys.argv[7] if len(sys.argv) > 7 else os.environ.get("LLM_API_KEY", "")
    buggy_file = sys.argv[8] if len(sys.argv) > 8 else None
    testinfo_file = sys.argv[9] if len(sys.argv) > 9 else None
    if not key:
        raise SystemExit("no API key: pass argv[7] or set LLM_API_KEY")

    with open(data_path) as f:
        entry = json.load(f)[idx]
    spec = entry.get("specification", "")
    if isinstance(spec, list):
        spec = "\n\n".join(str(x) for x in spec)

    init_fn, enh_fn = VERSIONS[version]
    if buggy_file and testinfo_file and os.path.exists(testinfo_file):
        system, user = enh_fn(entry["code"], open(buggy_file).read().strip(),
                              open(testinfo_file).read(), spec)
    else:
        system, user = init_fn(entry["code"], spec)

    client = OpenAI(api_key=key, base_url=endpoint, timeout=900, max_retries=2)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.7,
        max_tokens=16384,
    )
    raw = (resp.choices[0].message.content or "").strip()
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bug_raw.txt"), "w") as f:
        f.write(raw)
    obj = parse_bug_json(raw)
    code = (obj.get("buggy_code") or "").strip()
    with open(os.path.join(out_dir, "buggy_code.java"), "w") as f:
        f.write(code)
    with open(os.path.join(out_dir, "bug_parsed.json"), "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print(json.dumps({"out_dir": out_dir, "buggy_len": len(code),
                      "same_as_orig": code == entry["code"],
                      "completion_tokens": getattr(resp.usage, "completion_tokens", None)}))


if __name__ == "__main__":
    main()
