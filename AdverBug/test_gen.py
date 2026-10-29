import os
import json
import openai
from openai import OpenAI
from llm_config import LLMConfig
from usage_tracker import usage_tracker
import logging
import re
import fnmatch
import shlex
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_PRODUCTION_TOOL_CALLS = 5
MAX_SEARCH_RESULTS = 50
MAX_TOOL_OUTPUT_CHARS = 12000
MAX_READ_LINES = 600
MAX_PRODUCTION_COMMAND_CHARS = 8000
MAX_PRODUCTION_COMMAND_SECONDS = 10

PRODUCTION_CODE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "production_bash",
            "description": (
                "Run a read-only, Bash-shaped production-code query. Only the allowlisted "
                "commands grep, find, sed -n, head, and tail are accepted; commands may be "
                "joined with &&. The implementation exposes Java files under src/main only. "
                "Existing tests, arbitrary shell execution, file writes, and build commands "
                "are unavailable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "One or more allowed read-only commands joined with &&. Examples: "
                            "grep -R -n 'FileDecryptionProperties' . && find . -name '*Properties*.java'; "
                            "sed -n '1,220p' parquet-hadoop/src/main/java/.../Type.java"
                        ),
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
]


def production_exploration_instructions(max_calls: int = MAX_PRODUCTION_TOOL_CALLS,
                                        result_description: str = "complete test class") -> str:
    return f"""Production-code exploration:
- You may call the read-only `production_bash` tool before returning the
  {result_description}. It accepts Bash-shaped commands, and you may connect
  any number of allowed commands with `&&`, as in a mini-SWE agent.
- You have at most {max_calls} `production_bash` calls for this request. Plan searches
  before calling the tool and return the {result_description} when the budget
  is exhausted.
- Allowed commands only: `grep` (search), `find` (locate Java files),
  `sed -n`, `head`, and `tail` (read Java source excerpts). Typical examples:
  `grep -R -n 'FileDecryptionProperties' . && find . -name '*Properties*.java'`
  and `sed -n '1,240p' parquet-hadoop/src/main/java/.../Type.java`.
- Do not attempt any other command, pipe, redirect, substitution, build,
  interpreter, network, Git, or file-modification operation: it is rejected.
- Inspect unfamiliar project types and APIs instead of inventing constructors,
  builders, helpers, enum values, fields, overrides, or method signatures.
- When compiler feedback reports `cannot find symbol`, `incompatible types`,
  `no suitable method`, or an invalid `@Override`, inspect the relevant
  production declaration before correcting the test.
- The tool exposes production code only; existing test source is unavailable."""


def _testbed_root() -> Path:
    return Path(os.getenv("ADVER_TESTBED_ROOT", "/testbed")).resolve()


def _relative_testbed_path(path: Path) -> str:
    try:
        return path.relative_to(_testbed_root()).as_posix()
    except ValueError:
        return str(path)


def search_production_code(query: str) -> str:
    """Search Java files under src/main without exposing existing tests."""
    query = str(query or "").strip()
    if not query:
        return "ERROR: query must be a non-empty string."
    if len(query) > 200:
        return "ERROR: query is too long; search for one symbol or short literal."

    root = _testbed_root()
    needle = query.casefold()
    results = []
    for path in root.glob("**/src/main/**/*.java"):
        if not path.is_file():
            continue
        relative = _relative_testbed_path(path)
        if needle in path.name.casefold():
            results.append(f"{relative}:1: [filename match]")
            if len(results) >= MAX_SEARCH_RESULTS:
                break
        try:
            with path.open("r", encoding="utf-8", errors="replace") as source:
                for line_number, line in enumerate(source, start=1):
                    if needle in line.casefold():
                        results.append(f"{relative}:{line_number}: {line.rstrip()}")
                        if len(results) >= MAX_SEARCH_RESULTS:
                            break
        except OSError as error:
            results.append(f"{relative}: ERROR reading file: {error}")
        if len(results) >= MAX_SEARCH_RESULTS:
            break

    if not results:
        return f"No production Java matches found for {query!r}. Do not invent this API."
    output = "\n".join(results)
    if len(output) > MAX_TOOL_OUTPUT_CHARS:
        output = output[:MAX_TOOL_OUTPUT_CHARS] + "\n... [search output truncated]"
    return output


def _best_matching_production_file(query: str) -> Path | None:
    """Return a deterministic, source-backed best match for search_and_read."""
    query = str(query or "").strip()
    if not query or len(query) > 200:
        return None
    needle = query.casefold()
    candidates = []
    for path in _testbed_root().glob("**/src/main/**/*.java"):
        if not path.is_file():
            continue
        score = 0
        if needle in path.name.casefold():
            score += 100
        try:
            with path.open("r", encoding="utf-8", errors="replace") as source:
                for line in source:
                    if needle in line.casefold():
                        score += 10
                        break
        except OSError:
            continue
        if score:
            candidates.append((-score, _relative_testbed_path(path), path))
    return min(candidates)[2] if candidates else None


def search_and_read_production_code(query: str, start_line: int = 1,
                                    end_line: int | None = None) -> str:
    """Search then inspect the best matching production source in one action."""
    query = str(query or "").strip()
    if not query:
        return "ERROR: query must be a non-empty string."
    candidate = _best_matching_production_file(query)
    if candidate is None:
        return f"No production Java matches found for {query!r}. Do not invent this API."
    return (f"BEST MATCH for {query!r}: {_relative_testbed_path(candidate)}\n"
            f"{read_production_file(_relative_testbed_path(candidate), start_line, end_line)}")


def _validated_production_file(path: str) -> Path:
    root = _testbed_root()
    candidate = Path(str(path or ""))
    candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("path is outside /testbed") from error
    parts = relative.parts
    is_production = any(
        parts[index:index + 2] == ("src", "main")
        for index in range(max(0, len(parts) - 1))
    )
    if not is_production or candidate.suffix != ".java":
        raise ValueError("only Java files below src/main may be read")
    if not candidate.is_file():
        raise FileNotFoundError(f"production file not found: {relative.as_posix()}")
    return candidate


def read_production_file(path: str, start_line: int = 1,
                         end_line: int | None = None) -> str:
    """Read a bounded production Java source range with stable line numbers."""
    try:
        candidate = _validated_production_file(path)
        start = max(1, int(start_line or 1))
        requested_end = int(end_line) if end_line is not None else None
    except (OSError, TypeError, ValueError) as error:
        return f"ERROR: {error}"
    if requested_end is not None and requested_end < start:
        return "ERROR: end_line must be greater than or equal to start_line."

    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    end = min(len(lines), requested_end or len(lines), start + MAX_READ_LINES - 1)
    selected = lines[start - 1:end]
    numbered = "\n".join(
        f"{line_number:>6}  {line}"
        for line_number, line in enumerate(selected, start=start)
    )
    header = (f"FILE: {_relative_testbed_path(candidate)} "
              f"(lines {start}-{end} of {len(lines)})")
    if end < len(lines) and requested_end is None:
        numbered += (f"\n... [file truncated; call production_bash with "
                     f"sed -n '{end + 1},{end + MAX_READ_LINES}p' <path>]" )
    output = f"{header}\n{numbered}"
    if len(output) > MAX_TOOL_OUTPUT_CHARS:
        return output[:MAX_TOOL_OUTPUT_CHARS] + "\n... [file output truncated]"
    return output


def _split_production_command_chain(command: str) -> list[str]:
    """Split a Bash-shaped ``&&`` chain without running a shell."""
    command = str(command or "").strip()
    if not command:
        raise ValueError("command must be a non-empty string")
    if len(command) > MAX_PRODUCTION_COMMAND_CHARS:
        raise ValueError(f"command exceeds {MAX_PRODUCTION_COMMAND_CHARS} characters")

    commands, current = [], []
    quote = None
    escaped = False
    for index, character in enumerate(command):
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\":
            current.append(character)
            escaped = True
            continue
        if quote:
            current.append(character)
            if character == quote:
                quote = None
            continue
        if character in ("'", '"'):
            quote = character
            current.append(character)
            continue
        if (character == "&" and index > 0 and command[index - 1] == "&"
                and not (index > 1 and command[index - 2] == "&")):
            continue
        if character == "&":
            if index + 1 < len(command) and command[index + 1] == "&":
                part = "".join(current).strip()
                if not part:
                    raise ValueError("empty command before &&")
                commands.append(part)
                current = []
                continue
            raise ValueError("only && may join allowed commands")
        if character in ";|<>`$()\r\n":
            raise ValueError(f"unsupported shell syntax: {character!r}")
        current.append(character)
    if quote:
        raise ValueError("unterminated quoted string")
    part = "".join(current).strip()
    if not part:
        raise ValueError("empty command after &&")
    commands.append(part)
    return commands


def _safe_search_path(path: str) -> bool:
    """Accept only harmless path hints; the implementation still searches src/main."""
    path = str(path or "")
    return (path in (".", "./") or
            (not Path(path).is_absolute() and ".." not in Path(path).parts and
             "src/test" not in path.replace("\\", "/")))


def _find_production_files(pattern: str) -> str:
    pattern = str(pattern or "").strip()
    if not pattern or len(pattern) > 200:
        return "ERROR: find requires a short -name pattern."
    matches = []
    for path in _testbed_root().glob("**/src/main/**/*.java"):
        if path.is_file() and fnmatch.fnmatch(path.name, pattern):
            matches.append(_relative_testbed_path(path))
            if len(matches) >= MAX_SEARCH_RESULTS:
                break
    return "\n".join(matches) if matches else f"No production Java files match {pattern!r}."


def _read_tail_production_file(path: str, count: int) -> str:
    try:
        candidate = _validated_production_file(path)
        count = max(1, min(int(count), MAX_READ_LINES))
    except (OSError, TypeError, ValueError) as error:
        return f"ERROR: {error}"
    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, len(lines) - count + 1)
    return read_production_file(_relative_testbed_path(candidate), start, len(lines))


def _production_source_roots() -> list[str]:
    """Return shell-safe, testbed-relative src/main roots for real Bash commands."""
    root = _testbed_root()
    return sorted(
        _relative_testbed_path(path)
        for path in root.glob("**/src/main")
        if path.is_dir()
    )


def _compile_production_bash_command(command: str) -> str:
    """Validate one command and render its safe canonical Bash equivalent.

    The returned command is later executed by ``bash -c``. Every program,
    argument, and accessible path has been validated or generated here, so the
    model never gets arbitrary shell access.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as error:
        raise ValueError(f"invalid command quoting: {error}") from error
    if not tokens:
        raise ValueError("empty command")
    program, args = tokens[0], tokens[1:]
    roots = _production_source_roots()
    if not roots:
        raise ValueError("no src/main directories are available")

    if program == "grep":
        options = []
        positional = []
        index = 0
        while index < len(args):
            token = args[index]
            if token in ("-R", "-r", "--recursive", "-n", "--line-number", "-i", "--ignore-case"):
                options.append(token)
                index += 1
            elif token.startswith("-"):
                raise ValueError(f"unsupported grep option {token!r}")
            else:
                positional.append(token)
                index += 1
        if not positional:
            raise ValueError("grep requires a search query")
        query, paths = positional[0], positional[1:]
        if not all(_safe_search_path(path) for path in paths):
            raise ValueError("grep may search only relative production-code paths")
        grep_options = ["-R", "-n", "-E", "--include=*.java"]
        if any(option in ("-i", "--ignore-case") for option in options):
            grep_options.append("-i")
        return " ".join([
            "grep", *grep_options, "--", shlex.quote(query), *map(shlex.quote, roots),
        ])

    if program == "find":
        if len(args) != 3 or args[1] != "-name" or not _safe_search_path(args[0]):
            raise ValueError("supported find form is: find . -name '<pattern>.java'")
        pattern = args[2]
        if "/" in pattern or not pattern.endswith(".java"):
            raise ValueError("find pattern must match a Java filename only")
        return " ".join([
            "find", *map(shlex.quote, roots), "-type", "f", "-name", shlex.quote(pattern),
        ])

    if program == "sed":
        if len(args) != 3 or args[0] != "-n":
            raise ValueError("supported sed form is: sed -n 'START,ENDp' <production-java-path>")
        match = re.fullmatch(r"(\d+)(?:,(\d+))?p", args[1])
        if not match:
            raise ValueError("sed range must be START,ENDp or STARTp")
        candidate = _validated_production_file(args[2])
        return " ".join([
            "sed", "-n", shlex.quote(args[1]), shlex.quote(_relative_testbed_path(candidate)),
        ])

    if program in ("head", "tail"):
        if len(args) != 3 or args[0] not in ("-n", "--lines"):
            raise ValueError(
                f"supported {program} form is: {program} -n <lines> <production-java-path>")
        try:
            count = int(args[1])
        except ValueError:
            raise ValueError("line count must be an integer") from None
        if count < 1 or count > MAX_READ_LINES:
            raise ValueError(f"line count must be between 1 and {MAX_READ_LINES}")
        candidate = _validated_production_file(args[2])
        return " ".join([
            program, "-n", str(count), shlex.quote(_relative_testbed_path(candidate)),
        ])

    raise ValueError(
        f"command {program!r} is not allowed; use grep, find, sed -n, head, or tail")


def _execute_production_tool(name: str, arguments: str) -> str:
    try:
        values = json.loads(arguments or "{}")
        if not isinstance(values, dict):
            raise ValueError("tool arguments must be a JSON object")
        if name != "production_bash":
            return f"ERROR: unknown tool {name!r}."
        commands = _split_production_command_chain(values.get("command", ""))
        safe_command = " && ".join(
            _compile_production_bash_command(command) for command in commands)
        result = subprocess.run(
            ["bash", "-c", safe_command],
            cwd=_testbed_root(),
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
                 "LANG": "C", "LC_ALL": "C"},
            capture_output=True,
            text=True,
            timeout=MAX_PRODUCTION_COMMAND_SECONDS,
            check=False,
        )
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if len(output) > MAX_TOOL_OUTPUT_CHARS:
            output = output[:MAX_TOOL_OUTPUT_CHARS] + "\n... [tool output truncated]"
        return f"$ {values['command']}\n[returncode: {result.returncode}]\n{output}"
    except subprocess.TimeoutExpired:
        return (f"ERROR: production_bash exceeded {MAX_PRODUCTION_COMMAND_SECONDS} seconds; "
                "use a narrower query")
    except (TypeError, ValueError, OSError) as error:
        return f"ERROR: invalid production_bash command: {error}"


def _exploration_log_summary(arguments: str) -> str:
    """Return a compact safe description of a production_bash invocation."""
    try:
        return str(json.loads(arguments or "{}").get("command", ""))[:240]
    except (TypeError, ValueError, AttributeError):
        return ""


def _tools_parameter_unsupported(error: Exception) -> bool:
    message = str(error).casefold()
    mentions_tools = "tool" in message or "function call" in message
    rejected_parameter = any(token in message for token in (
        "unsupported", "not support", "unknown parameter", "unrecognized",
        "invalid parameter", "extra inputs", "not permitted",
    ))
    return mentions_tools and rejected_parameter


_RAW_PRODUCTION_BASH_CALL = re.compile(
    r"^\s*(?:<tool_call>\s*)?<function=production_bash>\s*"
    r"<parameter=command>\s*(.*?)\s*</parameter>\s*"
    r"</function>\s*(?:</tool_call>)?\s*$",
    flags=re.DOTALL,
)


def _raw_production_bash_command(content: str | None) -> str | None:
    """Decode Qwen/OpenRouter's textual rendering of a function call.

    Some OpenAI-compatible gateways expose Qwen's native tool syntax in
    ``message.content`` rather than populating ``message.tool_calls``.  It is
    a real tool request, not a Java compilation unit, so recognize it before
    finalizing a generation response.
    """
    if not content:
        return None
    match = _RAW_PRODUCTION_BASH_CALL.match(content)
    return match.group(1).strip() if match else None


def call_with_production_tools(client, model: str, messages: list[dict], *,
                               max_tokens: int = 16384,
                               temperature: float = 0.2,
                               max_tool_calls: int = MAX_PRODUCTION_TOOL_CALLS) -> str:
    """Run a small read-only exploration loop and return the model's final text."""
    conversation = list(messages)
    used_calls = 0
    tools_supported = True

    def final_tool_result(observation: str) -> str:
        """Turn the final tool observation into an explicit agent handoff.

        Some tool-capable models keep requesting searches even after seeing a
        useful result.  The request following the last permitted call has no
        tool schema, so make the required transition to the final Java source
        unambiguous in that last tool message as well.
        """
        return (
            f"{observation}\n\n"
            "TOOL BUDGET EXHAUSTED: Do not call any more tools. "
            "Now return only the complete executable Java test source requested "
            "by the user, with no explanation or Markdown fences."
        )

    while True:
        request = {
            "model": model,
            "messages": conversation,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools_supported and used_calls < max_tool_calls:
            request.update({"tools": PRODUCTION_CODE_TOOLS, "tool_choice": "auto"})
        try:
            response = client.chat.completions.create(**request)
        except Exception as error:
            # Some OpenAI-compatible gateways reject the tools field even for
            # otherwise supported models. Preserve the old one-shot behavior.
            if (tools_supported and "tools" in request
                    and _tools_parameter_unsupported(error)):
                logger.warning("Tool-enabled request failed; retrying without tools: %s", error)
                tools_supported = False
                continue
            raise

        usage_tracker.record(model, response)

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            raw_command = _raw_production_bash_command(message.content)
            if raw_command is None:
                return message.content or ""

            # Qwen via OpenRouter may render function calls in its native XML
            # syntax despite an OpenAI tool schema being supplied.  Feed the
            # observation back through the standard OpenAI-compatible tool
            # message protocol and continue the agent loop.
            call_id = f"raw-production-bash-{used_calls + 1}"
            serialized_call = {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "production_bash",
                    "arguments": json.dumps({"command": raw_command}),
                },
            }
            conversation.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [serialized_call],
            })
            if used_calls >= max_tool_calls:
                observation = ("ERROR: production-code exploration budget exhausted; "
                               "return the complete test class now.")
            else:
                used_calls += 1
                details = _exploration_log_summary(serialized_call["function"]["arguments"])
                print(
                    f"[{model}] 模型探索生产代码: production_bash "
                    f"({used_calls}/{max_tool_calls}) {details}",
                    flush=True)
                observation = _execute_production_tool(
                    "production_bash", serialized_call["function"]["arguments"])
                if used_calls == max_tool_calls:
                    observation = final_tool_result(observation)
            conversation.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": observation,
            })
            continue

        serialized_calls = []
        for call in tool_calls:
            serialized_calls.append({
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            })
        conversation.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": serialized_calls,
        })

        for call in tool_calls:
            if used_calls >= max_tool_calls:
                observation = "ERROR: production-code exploration budget exhausted; return the complete test class now."
            else:
                used_calls += 1
                details = _exploration_log_summary(call.function.arguments)
                print(
                    f"[{model}] 模型探索生产代码: {call.function.name} "
                    f"({used_calls}/{max_tool_calls}) {details}",
                    flush=True)
                observation = _execute_production_tool(
                    call.function.name, call.function.arguments)
                if used_calls == max_tool_calls:
                    observation = final_tool_result(observation)
            conversation.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": observation,
            })


def specification_text(specification) -> str:
    """Render extractor output consistently for bug and test generation prompts."""
    if not specification:
        return "(No specification was supplied; derive only clearly supported behavior.)"
    if isinstance(specification, list):
        return "\n\n".join(str(item) for item in specification if item)
    return str(specification)


def test_framework(function_info: dict) -> str:
    """Return the configured JUnit variant; default matches the Flink benchmark."""
    raw = str(function_info.get("test_framework", "junit5")).lower().replace(" ", "")
    if raw in {"junit4", "junit-4", "junit"}:
        return "junit4"
    return "junit5"


def java_version(function_info: dict) -> str:
    return str(function_info.get("java_version", "17"))


def method_context(function_info: dict) -> str:
    """Compact type-focused context used by test-generation prompts."""
    class_info = {
        "class_name": (
            function_info.get("full_class_name")
            or function_info.get("class_name")
            or "(unknown)"
        ),
        "constructors": function_info.get("class_constructor", []),
    }
    fields = function_info.get("class_fields") or []
    if fields:
        class_info["fields"] = fields
    # Related type declarations carry usable API shape (nested types,
    # factories, builders) more reliably than arbitrary dependency snippets.
    # Deliberately do not include related_tests or empty placeholders.
    related_types = function_info.get("related_types") or []
    if related_types:
        class_info["related_types"] = related_types
    return str(class_info)


def extract_java_code(content: str) -> str:
    """Extract Java source when the model mixes prose and code.

    Models do not always honor the requested Markdown fence.  In that case
    locate the first Java top-level declaration and discard any explanation
    before/after it.  The fallback keeps the original text so a caller can
    still send it to the repair path when no Java marker is recognizable.
    """
    if not content:
        return ""
    content = content.strip()

    fenced = re.search(r"```(?:java)?\s*(.*?)```", content,
                       flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced.group(1).strip()

    start_pattern = re.compile(
        r"^\s*(?:package\s+[\w.]+\s*;|"
        r"import\s+(?:static\s+)?[\w.*]+\s*;|"
        r"(?:@[A-Za-z_$][\w$]*(?:\([^\n]*\))?\s*)+|"
        r"(?:(?:public|protected|private|abstract|final|sealed|non-sealed)\s+)*"
        r"(?:class|interface|enum|record)\s+[A-Za-z_$][\w$]*)",
        flags=re.MULTILINE,
    )
    match = start_pattern.search(content)
    if match:
        content = content[match.start():].lstrip()

    # If prose follows an unfenced class, the final Java brace is a safe
    # boundary for the common generated-test shape.
    end = content.rfind("}")
    if end >= 0:
        content = content[:end + 1]
    return content.strip()


def expected_test_class_name(function_info: dict) -> str:
    """Return the public test class required by the requested test path."""
    filename = os.path.basename(function_info.get("test_file", ""))
    return filename[:-5] if filename.endswith(".java") else filename


def infer_test_package(function_info: dict) -> str:
    """Infer the package from test_file, falling back to the target class FQN."""
    test_file = (function_info.get("test_file") or "").replace("\\", "/")
    marker = "/src/test/java/"
    normalized = f"/{test_file.lstrip('/')}"
    if marker in normalized:
        relative = normalized.split(marker, 1)[1]
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        if parent:
            return parent.replace("/", ".")

    full_class_name = function_info.get("full_class_name") or ""
    if "." in full_class_name:
        return full_class_name.rsplit(".", 1)[0]
    return ""


def normalized_source_imports(function_info: dict) -> list[str]:
    """Normalize extractor imports into complete Java import statements."""
    raw_imports = function_info.get("imports") or function_info.get("import") or []
    if isinstance(raw_imports, str):
        raw_imports = raw_imports.splitlines()
    imports = []
    for value in raw_imports:
        statement = str(value).strip()
        if not statement:
            continue
        if not statement.startswith("import "):
            statement = f"import {statement}"
        if not statement.endswith(";"):
            statement += ";"
        if statement not in imports:
            imports.append(statement)
    return imports


IMPORT_PATTERN = re.compile(
    r"^\s*import\s+(static\s+)?"
    r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;\s*$"
)


def model_test_imports(source: str, function_info: dict) -> list[str]:
    """Keep safe explicit imports supplied by a generated test.

    Package and framework ownership remains with the runner, but test code often
    needs helpers that the production method did not import (for example Jackson
    test builders). Maven remains the authority on whether an imported type is
    available on this module's test classpath.
    """
    framework = test_framework(function_info)
    expected_class = expected_test_class_name(function_info)
    target_class = function_info.get("full_class_name") or ""
    imports = []
    for line in source.splitlines():
        match = IMPORT_PATTERN.match(line)
        if not match:
            continue
        is_static = bool(match.group(1))
        qualified_name = match.group(2)
        if qualified_name.endswith(".*"):
            continue
        # JUnit's baseline imports are fixed by the runner. Extra JUnit 5
        # annotations/extensions are valid for a Jupiter suite, but never mix
        # framework generations.
        if qualified_name.startswith("org.junit."):
            if framework != "junit5" or not qualified_name.startswith("org.junit.jupiter."):
                continue
            if qualified_name in {
                "org.junit.jupiter.api.Test",
                "org.junit.jupiter.api.Assertions",
            }:
                continue
        if not is_static:
            if qualified_name.rsplit(".", 1)[-1] == expected_class:
                continue
            if target_class and qualified_name == target_class:
                continue
        statement = f"import {'static ' if is_static else ''}{qualified_name};"
        if statement not in imports:
            imports.append(statement)
    return imports


def fixed_test_imports(function_info: dict, source_body: str = "",
                       generated_imports: list[str] | None = None) -> list[str]:
    """Merge runner-owned imports with sanitized, explicit model imports."""
    if test_framework(function_info) == "junit4":
        imports = ["import org.junit.Test;", "import static org.junit.Assert.*;"]
    else:
        imports = [
            "import org.junit.jupiter.api.Test;",
            "import static org.junit.jupiter.api.Assertions.*;",
        ]
    reserved_names = {"Test", "Assertions"}
    imported_names = set(reserved_names)

    target_class = function_info.get("full_class_name") or ""
    target_package = target_class.rsplit(".", 1)[0] if "." in target_class else ""
    test_package = infer_test_package(function_info)
    if target_class and target_package != test_package:
        imports.append(f"import {target_class};")
        imported_names.add(target_class.rsplit(".", 1)[-1])

    candidate_imports = list(generated_imports or [])
    # Production imports may contain a framework from a different test setup;
    # only model imports have already been checked against the active framework.
    candidate_imports.extend(
        statement for statement in normalized_source_imports(function_info)
        if not statement.startswith("import org.junit.")
        and not statement.startswith("import static org.junit.")
    )
    for statement in candidate_imports:
        match = re.match(r"import\s+(?:static\s+)?([\w.]+)(?:\.\*)?;", statement)
        simple_name = match.group(1).rsplit(".", 1)[-1] if match else ""
        is_wildcard = statement.endswith(".*;")
        is_static = statement.startswith("import static ")
        if is_wildcard:
            continue
        referenced = (
            re.search(rf"\b{re.escape(simple_name)}\s*\(", source_body)
            if is_static
            else re.search(rf"\b{re.escape(simple_name)}\b", source_body)
        )
        if not referenced:
            continue
        if not is_wildcard and simple_name in imported_names:
            continue
        if statement not in imports:
            imports.append(statement)
            if simple_name and not is_wildcard:
                imported_names.add(simple_name)
    return imports


def fixed_test_header(function_info: dict, source_body: str = "",
                      generated_imports: list[str] | None = None) -> str:
    """Build the package/import header that replaces any model-generated header."""
    lines = []
    package_name = infer_test_package(function_info)
    if package_name:
        lines.extend([f"package {package_name};", ""])
    lines.extend(fixed_test_imports(function_info, source_body, generated_imports))
    return "\n".join(lines)


def java_compilation_context(function_info: dict) -> str:
    """Build minimal compilation guidance for generation and repair.

    The model owns the complete package/import header. Keep the context compact
    so it derives imports from production exploration and compiler diagnostics,
    rather than from an incidental production-import list.
    """
    return f"""Required top-level test class: {expected_test_class_name(function_info)}
Configured test framework: {test_framework(function_info)}
Configured Java version: {java_version(function_info)}
Test source path: {function_info.get('test_file') or '(unknown)'}"""


class TestGenerationAgent:
    def __init__(self, llm_config: LLMConfig, *, use_production_tools: bool = True):
        self.llm_config = llm_config
        self.client = OpenAI(api_key=self.llm_config.API_KEY,
                             base_url=self.llm_config.API_ENDPOINT,
                             timeout=self.llm_config.REQUEST_TIMEOUT,
                             max_retries=0)
        self.model = self.llm_config.MODEL_NAME
        self.use_production_tools = use_production_tools

    def init_test_prompt(self, erroneous_code: str, function_info: dict) -> str:
        system_prompt = """You are a professional test engineer specializing in writing high-quality unit test code"""

        function_name = function_info.get('name', '(unknown)')
        specification = specification_text(function_info.get('specification'))
        file_path = function_info.get('src_file', '(unknown)')
        compilation_context = java_compilation_context(function_info)
        context = method_context(function_info)

#         user_prompt = f"""
# Please generate a test class for the following function.

# Function Information:
# - Src file: {file_path}
# - Function name: {function_name}
# - Class: {class_info if class_name else 'Standalone function'}

# Function Code:
# ```java
# {erroneous_code}
# ```

# Requirements:
# Use JUnit 5 framework for writing tests.
# Your job is to output a corresponding test class that focuses on detecting errors and unexpected behaviors in the code under test.
# The test code should be written into {test_path}. Please make sure the imports are correct.
# Return ONLY code without explanations, non-code text, or markdown formatting.

# ```java
# <test code>
# ```
# """   
#         user_prompt = f"""
# Your task is to design tests that ensure only correct implementations (following the specification) pass, while incorrect implementations would fail.
# You are given the following information:
# - Code under test
# - Specification

# Your tasks:
# 1. Infer the **intended behavior** from the specification.
# 2. Design a set of **test cases** that cover:
# - Basic functionality with valid inputs and expected outputs.
# - Boundary conditions and edge cases.
# - Invalid inputs and error handling.
# - Potential issues with dependency interactions.
# 3. Write executable test code using Java 17 and JUnit 5.
# 4. The test code should be written into {test_path}. Please make sure the imports are correct.
# 5. Ensure tests are designed to differentiate between correct and incorrect implementations:
# - At least one test should be able to expose an incorrect implementation if it does not fully follow the behavior of the specification.
# - A correct implementation should pass all tests.

# ## Input Method ({function_name}):
# ```java
# {erroneous_code}
# ```

# ## Method Context:
# - Src file: {file_path}
# - Class: {class_info if class_name else 'Standalone function'}

# ## Specification:
# {specification}


# ### Output Format ###:
# Return ONLY code without explanations, non-code text, or markdown formatting.
# ```java
# <test code>
# ```
# """
#         
        user_prompt = f"""
Your job is to output a test class that invokes the code under test.
The supplied implementation may contain defects. Treat the specification as the
primary source of truth for expected behavior. Actively inspect related
production code to understand the public API and fill in details that the
specification leaves implicit: helper methods, related types, documentation,
and independent call sites are useful semantic evidence. Reconcile that
evidence with the specification instead of testing only its literal wording.
Do not copy constants, branches, arguments, or results from the supplied
implementation and treat them as expected behavior.

Your tasks:
1. Before writing code, reason step by step internally (do not output this
   reasoning): combine the specification with independently corroborated
   production-code evidence, identify the observable intended behavior, predict
   how the supplied implementation could differ from it, and choose an input
   and assertion that expose that difference.
2. Design tests that distinguish a correct implementation from the supplied
   implementation: derive assertions from the specification so correct code
   passes and the supplied code fails; prioritize inputs, state, or boundaries
   likely to expose a behavioral difference rather than current behavior.
3. Write a complete executable test source, including its package declaration
   and required imports.
- Include at least one enabled `@Test` that calls the target behavior and makes
  a non-trivial assertion derived from the specification.
- Do not use `@Disabled`, assumptions that skip execution, empty tests,
  `assertTrue(true)`, catch-and-ignore blocks, local replacement stubs, or
  expected values copied from the supplied implementation.

## Function ({function_name}):
```java
{erroneous_code}
```

## Specification:
{specification}

## Method Context:
- Src file: {file_path}
- Class context: {context}

## Required Compilation Context:
{compilation_context}

## Available read-only tools:
{production_exploration_instructions() if self.use_production_tools else 'No repository exploration tools are available. Use only the supplied context.'}


### Output Format ###:
Return only the complete Java compilation unit, including its package declaration
and all imports. Do not include Markdown fences or explanations.
"""

        message = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                    ]
        # return message
        try:
            if self.use_production_tools:
                response_text = call_with_production_tools(
                    self.client, self.model, message, temperature=0.2, max_tokens=16384)
            else:
                response = self.client.chat.completions.create(
                    model=self.model, messages=message, temperature=0.2, max_tokens=16384)
                usage_tracker.record(self.model, response)
                response_text = response.choices[0].message.content or ""
            test_code = extract_java_code(response_text)
            print(f"Generated test code ({len(test_code)} chars)")
            # if test_code.startswith("```java") and test_code.endswith("```"):
            #     test_code = test_code[len("```java"):-len("```")].strip()
            return test_code
        except Exception as e:
            logger.error(f"Error calling LLM for test generation: {e}")
            return "" # Return empty string on error


    def enhance_test_prompt(self, erroneous_code: str, function_info: dict, test: str) -> str:
        system_prompt = """You are a professional test engineer specializing in writing high-quality unit test code"""

        function_name = function_info.get('name', '(unknown)')

        # match = re.search(r'^def\s+\w+\([^)]*\)(?:\s*->\s*[^:]+)?:', function_code, re.MULTILINE)
        # if match:
        #     signature = match.group(0)

        specification = specification_text(function_info.get('specification'))
        file_path = function_info.get('src_file', '(unknown)')
        compilation_context = java_compilation_context(function_info)
        context = method_context(function_info)

#         user_prompt = f"""
# Please generate a test class for the following function.

# Function Information:
# - Src file: {file_path}
# - Function name: {function_name}
# - Class: {class_info if class_name else 'Standalone function'}

# Function Code:
# ```java
# {erroneous_code}
# ```

# Existing Test Code:
# ```java
# {test}
# ```

# Requirements:
# Use JUnit 5 framework for writing tests.
# Your job is to output a corresponding test class that focuses on detecting errors and unexpected behaviors in the code under test.
# The testcases must be different from the existing test code.
# The test code should be written into {test_path}. Please make sure the imports are correct.
# Return ONLY code without explanations, non-code text, or markdown formatting.

# ```java
# <test code>
# ```
# """

#         user_prompt = f"""
# Your task is to design tests that ensure only correct implementations (following the specification) pass, while incorrect implementations would fail.
# You are given the following information:
# - Code under test
# - Specification
# - Existing Test Code

# Your tasks:
# 1. Infer the **intended behavior** from the specification.
# 2. Design a set of **test cases** that cover:
# - Basic functionality with valid inputs and expected outputs.
# - Boundary conditions and edge cases.
# - Invalid inputs and error handling.
# - Potential issues with dependency interactions.
# 3. Write executable test code using Java 17 and JUnit 5.
# 4. The test code should be written into {test_path}. Please make sure the imports are correct.
# 5. Ensure tests are designed to differentiate between correct and incorrect implementations:
# - At least one test should be able to expose an incorrect implementation if it does not fully follow the behavior of the specification.
# - A correct implementation should pass all tests.
# 6. The generated test cases must be different from the existing test code.

# ## Input Method ({function_name}):
# ```java
# {erroneous_code}
# ```

# ## Method Context:
# - Src file: {file_path}
# - Class: {class_info if class_name else 'Standalone function'}

# ## Specification:
# {specification}

# ## Existing Test Code:
# ```java
# {test}
# ```

# ### Output Format ###:
# Return ONLY code without explanations, non-code text, or markdown formatting.
# ```java
# <test code>
# ```
# """

        user_prompt = f"""
Your job is to output corresponding test code that invokes the code under test.
The supplied implementation may contain defects. Treat the specification as the
primary source of truth. Actively inspect related production code to understand
the public API and fill in details that the specification leaves implicit:
helper methods, related types, documentation, and independent call sites are
useful semantic evidence. Reconcile that evidence with the specification
instead of testing only its literal wording. Do not copy constants, branches,
arguments, or results from the supplied implementation and treat them as
expected behavior.

Your tasks:
1. Before writing code, reason step by step internally (do not output this
   reasoning): combine the specification with independently corroborated
   production-code evidence, identify the observable intended behavior, predict
   how the supplied implementation could differ from it, and choose an input
   and assertion that expose that difference.
2. Design tests that distinguish a correct implementation from the supplied
   implementation: derive assertions from the specification so correct code
   passes and the supplied code fails; prioritize inputs, state, or boundaries
   likely to expose a behavioral difference rather than current behavior.
3. Write a complete executable test source, including its package declaration
   and required imports.
- Include at least one enabled `@Test` that invokes the target behavior and has
  a non-trivial assertion derived from the specification.
- Do not use disabled/empty tests, skip assumptions, tautological assertions,
  catch-and-ignore blocks, local replacement stubs, or expected values copied
  from the supplied implementation.
4. The generated test cases must be different from the existing test code.

## Function ({function_name}):
```java
{erroneous_code}
```

## Specification:
{specification}

## Method Context:
- Src file: {file_path}
- Class context: {context}

## Required Compilation Context:
{compilation_context}

## Available read-only tools:
{production_exploration_instructions()}


## Existing Test Code:
```java
{test}
```

### Output Format ###:
Return only the complete Java compilation unit, including its package declaration
and all imports. Do not include Markdown fences or explanations.
"""

        message = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                    ]
        # return message
        try:
            test_code = extract_java_code(call_with_production_tools(
                self.client, self.model, message, temperature=0.2, max_tokens=16384))
            # if test_code.startswith("```java") and test_code.endswith("```"):
            #     test_code = test_code[len("```java"):-len("```")].strip()
            return test_code
        except Exception as e:
            logger.error(f"Error calling LLM for test generation: {e}")
            return "" # Return empty string on error

    def fix_test_prompt(self, test: str, error: str, function_info=None) -> str:
        """Repair test mechanics without allowing the repair to erase coverage.

        Kept for compatibility with callers outside ``FilterTestGenerationAgent``.
        The filter path provides a richer, entry-aware version of this prompt.
        """
        function_info = function_info or {}
        prompt = f"""The tests below are failing with the following error message:
        Tests:
        ```java
        {test}
        ```

        Error:
        ```
        {error}
        ```

        Fix only compilation, setup, or test-framework API usage. Preserve each
        test's behavioral intent, target invocation, and specification-derived
        expected outcomes. Do not delete or disable tests, weaken assertions,
        change expected values merely to match the implementation, use skip
        assumptions or catch-and-ignore blocks, or replace a test with a
        tautology.

        {production_exploration_instructions()}

        Return the complete Java compilation unit, including its package
        declaration and imports, with no Markdown fences.
        """
        try:
            fixed_test_code = extract_java_code(call_with_production_tools(
                self.client, self.model,
                [{"role": "system", "content": "You are a helpful assistant that fixes failing test code."},
                 {"role": "user", "content": prompt}],
                temperature=0.2, max_tokens=16384))
            return fixed_test_code
        except Exception as e:
            logger.error(f"Error calling LLM for test fixing: {e}")
            return test # Return original test code on error

    


if __name__ == "__main__":
    # Example usage (will require actual API key and endpoint)
    llm_config_instance = LLMConfig(api_key=os.getenv("LLM_API_KEY", "YOUR_LLM_API_KEY"),
                                    api_endpoint=os.getenv("LLM_API_ENDPOINT", "https://api.apiyi.com/v1"),
                                    model_name=os.getenv("LLM_MODEL_NAME", "gpt-4o-mini"))

    agent = TestGenerationAgent(llm_config=llm_config_instance)
    sample_original_code = """
def add(a, b):
    return a + b
"""
    sample_buggy_code = """
def add(a, b):
    return a - b # Bug: should be a + b
"""
    print("原始代码:\n", sample_original_code)
    print("错误代码:\n", sample_buggy_code)

    # To run this, you'll need to set LLM_API_KEY environment variable
    # generated_tests = agent.generate_tests(sample_original_code, sample_buggy_code)
    # if generated_tests:
    #     print("\n生成的测试:\n", generated_tests[0])
    #     agent.integrate_with_execution_environment(generated_tests, {"test_output_dir": "./output_tests"})

    agent.integrate_with_execution_environment([], {"test_output_dir": "./output_tests"}) # Example to create dir
