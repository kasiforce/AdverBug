"""Auto-fix common compile errors in generated JUnit suites (mirrors the
pipeline's fix_compile role, implemented as deterministic rules).

Rules:
 0. TypeFactory.defaultInstance() -> createDefaultInstance(); ensure import.
    DeserializationFeature.READ_UNKNOWN_ENUM_VALUES_* -> EnumFeature.*.
 1. tools.jackson.annotation.* -> com.fasterxml.jackson.annotation.*
 2. JsonMappingException / JsonProcessingException -> tools.jackson.core.JacksonException
 3. import tools.jackson.databind.EnumFeature -> tools.jackson.databind.cfg.EnumFeature
 4. JsonMapper used but not imported -> import tools.jackson.databind.json.JsonMapper
 5. ObjectMapper X = new ObjectMapper(); X.enable/disable/configure(F...)...
    -> JsonMapper.builder()...build() chain (absorbing the feature calls).
"""
import re
import sys

ANNOT = re.compile(r'^import (tools\.jackson\.(?:databind\.)?annotation)\.(.+);$', re.M)

ENUM_CONSTS = ('READ_UNKNOWN_ENUM_VALUES_AS_NULL',
               'READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE',
               'READ_UNKNOWN_ENUM_VALUES_USING_SIZE')


def _fix_feature(feat):
    feat = feat.strip()
    for const in ENUM_CONSTS:
        if feat.endswith(const):
            return 'tools.jackson.databind.cfg.EnumFeature.' + const
    return feat


def _absorb_chains(src):
    lines = src.splitlines(keepends=True)
    out = []
    i = 0
    n = 0
    create = re.compile(r'^(\s*)(?:ObjectMapper|JsonMapper)\s+(\w+)\s*=\s*new ObjectMapper\(\);\s*$')
    call = re.compile(r'^\s*(\w+)\.(enable|disable|configure)\(([^)]+)\);\s*$')
    while i < len(lines):
        m = create.match(lines[i].rstrip('\n'))
        if not m:
            out.append(lines[i])
            i += 1
            continue
        ind, var = m.group(1), m.group(2)
        j = i + 1
        calls = []
        while j < len(lines):
            stripped = lines[j].strip()
            if stripped == '' or stripped.startswith('//') or stripped.startswith('/*'):
                j += 1
                continue
            cm = call.match(lines[j].rstrip('\n'))
            if cm and cm.group(1) == var:
                calls.append((cm.group(2), cm.group(3)))
                j += 1
                continue
            break
        if calls:
            n += 1
            out.append(f"{ind}ObjectMapper {var} = JsonMapper.builder()\n")
            for meth, args in calls:
                if meth == 'configure':
                    parts = [a.strip() for a in args.split(',')]
                    meth = 'enable' if parts[-1] == 'true' else 'disable'
                    args = parts[0]
                out.append(f"{ind}        .{meth}({_fix_feature(args)})\n")
            out.append(f"{ind}        .build();\n")
            i = j
        else:
            out.append(f"{ind}{var} = JsonMapper.builder().build();\n")
            i += 1
    return "".join(out), n


def fix(src):
    n = 0
    if 'TypeFactory.defaultInstance()' in src:
        src = src.replace('TypeFactory.defaultInstance()', 'TypeFactory.createDefaultInstance()')
        n += 1
    if 'TypeFactory' in src and 'import tools.jackson.databind.type.TypeFactory;' not in src:
        m = re.search(r'^import tools\.jackson\.databind\.(JavaType|ObjectMapper);$', src, re.M)
        if m:
            src = src.replace(m.group(0), m.group(0) +
                              '\nimport tools.jackson.databind.type.TypeFactory;', 1)
            n += 1
    for const in ENUM_CONSTS:
        src, k = re.subn(rf'\bDeserializationFeature\.({const})\b', r'EnumFeature.\1', src)
        n += k

    def annot_sub(m):
        return f"import com.fasterxml.jackson.annotation.{m.group(2)};"
    src, k = ANNOT.subn(annot_sub, src)
    n += k
    for old in ('JsonMappingException', 'JsonProcessingException'):
        if old in src:
            src = re.sub(rf'import (tools\.[\w.]+\.){old};',
                         'import tools.jackson.core.JacksonException;', src)
            src = src.replace(old, 'JacksonException')
            n += 1
    if 'import tools.jackson.databind.EnumFeature;' in src:
        src = src.replace('import tools.jackson.databind.EnumFeature;',
                          'import tools.jackson.databind.cfg.EnumFeature;')
        n += 1
    if re.search(r'\bEnumFeature\.', src) and 'import tools.jackson.databind.cfg.EnumFeature;' not in src:
        m = re.search(r'^import tools\.jackson\.databind\.(JavaType|ObjectMapper);$', src, re.M)
        if m:
            src = src.replace(m.group(0), m.group(0) +
                              '\nimport tools.jackson.databind.cfg.EnumFeature;', 1)
            n += 1
    if 'JsonMapper' in src and 'import tools.jackson.databind.json.JsonMapper;' not in src:
        m = re.search(r'^import tools\.jackson\.databind\.(\w+);$', src, re.M)
        if m:
            src = src.replace(m.group(0), m.group(0) +
                              '\nimport tools.jackson.databind.json.JsonMapper;', 1)
            n += 1
    src, k = _absorb_chains(src)
    n += k
    return src, n


if __name__ == "__main__":
    args = sys.argv[1:]
    ruleset = "none"
    if args and args[0] == "--ruleset":
        ruleset = args[1]
        args = args[2:]
    if ruleset == "none":
        print("no ruleset selected; pass --ruleset <name> to enable project-specific rules")
        raise SystemExit(0)
    for p in args:
        src = open(p).read()
        fixed, n = fix(src)
        if fixed != src:
            open(p, 'w').write(fixed)
        print(p, 'applied', n)
