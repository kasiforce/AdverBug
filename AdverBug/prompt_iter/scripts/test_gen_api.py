"""Generate tests via the REAL LLM API, mirroring the pipeline exactly:
- messages rendered by AdverBug/test_gen.py::init_test_prompt (via prompts_bridge monkeypatch capture)
- temperature 0, max_tokens 16384
- ```java fence extraction identical to test_gen.py

Usage:
  /data/home/cjy/miniconda3/envs/software-testing/bin/python scripts/test_gen_api.py \
      <entry_idx> <buggy_code_file> <out_file> [model] [endpoint] [api_key]

Defaults: model=gpt-4o-mini, endpoint=https://api.agicto.cn/v1,
key = $LLM_API_KEY (must be set or passed).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from prompts_bridge import render_init_test, load_entries  # noqa: E402
from openai import OpenAI  # noqa: E402


def main():
    idx = int(sys.argv[1])
    buggy_file = sys.argv[2]
    out = sys.argv[3]
    model = sys.argv[4] if len(sys.argv) > 4 else "gpt-4o-mini"
    endpoint = sys.argv[5] if len(sys.argv) > 5 else "https://api.agicto.cn/v1"
    key = sys.argv[6] if len(sys.argv) > 6 else os.environ.get("LLM_API_KEY", "")
    if not key:
        raise SystemExit("no API key: pass argv[6] or set LLM_API_KEY")

    entry = load_entries()[idx]
    buggy = open(buggy_file).read().strip()
    msgs = render_init_test(entry, buggy)

    client = OpenAI(api_key=key, base_url=endpoint, timeout=600, max_retries=2)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": msgs["system"]},
                  {"role": "user", "content": msgs["user"]}],
        temperature=0.0,
        max_tokens=16384,
    )
    content = (resp.choices[0].message.content or "").strip()
    with open(out + ".raw.txt", "w") as f:
        f.write(content)
    test = content.split("```java")[-1].split("```")[0].strip()
    with open(out, "w") as f:
        f.write(test)
    print(json.dumps({"out": out, "lines": len(test.splitlines()),
                      "model": model,
                      "completion_tokens": getattr(resp.usage, "completion_tokens", None)}))


if __name__ == "__main__":
    main()
