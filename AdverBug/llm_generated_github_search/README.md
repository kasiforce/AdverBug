# GitHub self-declared LLM-generated repository search

Audit date: 2026-10-29 (Asia/Shanghai).

## Reproducible inclusion rule

A repository is considered self-declared LLM-generated only when its public
README explicitly says that all, every line, or the entire source/code was
generated or written by a named AI/LLM. A repository is not included merely
because it uses an LLM at runtime, generates AI content, displays a generic
"built with" badge, or says that only its README/assets/tests were generated.

Benchmark candidates must additionally have an OSI-style license and at least
one production function satisfying the inclusive conjunction:

```text
LOC >= 100 AND cyclomatic complexity >= 10 AND syntactic call out-degree >= 5
```

The search used GitHub repository-search phrases including "written entirely
by Claude", "generated entirely by Claude", and "100% AI-generated", followed
by local README evidence matching and manual false-positive rejection. GitHub's
anonymous search cap and the top-30 result cap mean that this is a candidate
discovery audit, not an exhaustive census of GitHub.

## Verified positive results

| Repository | Language analyzed | License | Qualifying functions | Benchmark decision |
|---|---:|---:|---:|---|
| `WaschbaerImHaus/ai-generated-math-papers` | Python | MIT | 10 | Passes a five-functions-per-project minimum; strongest current candidate |
| `ligenjian001-ai/pdf_commenter` | Python | MIT | 2 | Keep only if the project minimum is one; mixed JS/Python/Swift stack |
| `saulmunn/sibling-marker` | Python | MIT | 1 | Keep only if the project minimum is one; Anki runtime dependency |
| `mitsuhiko/mini-presenter` | JavaScript | Apache-2.0 | 1 | Keep only if the project minimum is one; no repository test suite was found |

The exact frozen commits and per-function metrics are in
`verified_benchmark_candidates.csv`.

The strongest candidate declares that its papers, source, Python modules, and
tests were generated entirely by Claude Code, contains 165 discovered
production Python files and 3,369 extracted public functions, and yields 10
functions under the three-way AND filter. Its README claims more than 10,403
tests, while 138 test files were observed locally.

## Important benchmark caveat

`ai-generated-math-papers` has a large existing test corpus. If the agent can
read target-specific original tests, test generation may become retrieval or
adaptation rather than synthesis. Freeze the commit, remove or hide tests that
exercise each selected target from the agent-visible checkout, and keep those
tests only as evaluator-side regression tests. Also run each target in the
project environment before admitting it: the provenance statement and static
complexity metrics do not establish functional correctness.

## Negative complexity checks

The following explicitly disclosed and licensed candidates were cloned and
produced zero qualifying exported JavaScript functions under the same filter:
`The-Nils/LineMaker`, `mirkanu/gsd-dashboard`, `ofriw/sargel`,
`mbucc9000/encore`, `SpinEchoArcanist/action-kanban`,
`MateuszDabrowski/clockforce`, `hansafumoonga/computer_club`,
`liulanci/MediBot`, `thith/aicademy-demo`,
`agentic-ai-humans/google-ai-studio-chat-branches`, `gtdong/litegame`,
`HenryLin1134/web-dev-agent-toolkit`, and `FishCityBee/todo-task-tool`.

The following Python candidates also yielded zero:
`chr1shaefn3r/grow-up`, `Balneo/budgetsim`,
`DavidLittle/uk-cgt-calculator`, `falko-strenzke/taskwarrior-youtrack`,
`miyako31/MemoryMonitor-py`, and `xbc5/bookmark`.

## Files

- `search_github.py`: discovery and README evidence collection script.
- `search_candidates.csv` / `search_results.json`: first JavaScript search batch.
- `search_candidates_python.csv` / `search_results_python.json`: first Python search batch.
- `verified_benchmark_candidates.csv`: manually verified positive projects and
  exact function metrics at frozen commits.

## Extended JavaScript search

A second search targeted low-star repositories larger than 300 KB and used
additional provenance phrases such as "every line of code", "no human-written
code", and "all source code". Web search was also used because anonymous GitHub
repository search repeatedly hit its shared rate limit.

The major result is `davidbau/menace-classic`. Its README says that the project
is a complete JavaScript reimplementation written entirely by AI coding agents,
contains no human-written code, and that agents wrote every line of code, every
test, and all documentation. At commit
`41fce5473e3cf766736c8da32529d0525c919849`, the extractor discovered 403
production JavaScript files and 5,674 exported functions; 95 functions satisfy
the three-way AND filter. Candidate medians are LOC 130, CC 69, and call
out-degree 25. This is substantially harder than the other discovered
JavaScript projects.

However, the repository uses the NetHack General Public License (SPDX: NGPL).
The current JavaScript acquisition whitelist contains only MIT, Apache-2.0,
BSD-3-Clause, and ISC. Because the intended benchmark will be publicly
released, `menace-classic` is excluded from the formal candidate set despite
its excellent complexity profile. Its measurements are retained only as an
auditable exclusion record and must not be counted in the benchmark dataset.

Additional MIT-licensed results are `sparkle` (3 qualifying functions) and
`VibedGames-benchmark` (2). `greendefense` yields 3, but the author labels the
whole project 99% AI-coded because of downloaded assets and a few manual CSS
adjustments, so it belongs in a near-complete rather than pure stratum.
`GitLobster` yields exactly 5, but the all-AI declaration is on its owning
organization's profile rather than its repository README; retain it as a
provisional candidate until repository-level provenance is recorded.

Exact project-level results and frozen commits are in
`javascript_extended_summary.csv`. The 95-function extractor output for
`menace-classic` was produced locally at `/tmp/menace-classic_js_ext.json`.

### Later JavaScript search rounds

Additional searches used the phrases "written entirely by AI", "not a single
line of code", and "built entirely by AI", with repository-size lower bounds.
The new eligible result is `yangbaibai-ops/Lumin` (MIT, explicit repository-level
AI authorship), which yields two qualifying exported JavaScript functions at
commit `e1ae0fdf4bb02da1a241dbf986d0e3a4aafea5aa`. Both functions are under
`tools/lib/` rather than the application's core UI, so Lumin should be labelled
as a development-tool target if admitted.

The following newly screened, explicitly disclosed projects yielded zero under
the three-way AND predicate: `cardpay/unlimeety`,
`davidcox/ai-slop-detector`, `Mollapsar/MOWAY`, `sh4ka/homepage`,
`hope61/blackwall`, `taiwbi/pkgdump`, `TheBoredTeam/boring.website`, and
`ApplesDaddy/mao-online`. Consequently, no newly found JavaScript repository
simultaneously has strong repository-level provenance, a whitelisted license,
and at least five qualifying exported functions.
