---
name: script-review
description: Code review process for a script and any subscripts.
---

# Script code review

Perform a code review of script flow and evaluate inefficencies in logic and flow.

**CRITICAL** Debugging breakpoints within FileMaker scripts are not an issue with regards to runtime execution. Breakpoints are only considered/used when a developer specifically invokes the FileMaker debugger.

## Two script formats — know the difference

There are two distinct XML formats in this project. They are **not interchangeable**:

| Format                             | Location                             | Format name                                                               | Usable as output?                   |
| ---------------------------------- | ------------------------------------ | ------------------------------------------------------------------------- | ----------------------------------- |
| FileMaker "Save As XML" export     | `agent/xml_parsed/scripts/`          | Verbose, uses `<ParameterValues>`, `<Options>`, `hash` attributes         | **No** — read-only reference only   |
| FileMaker clipboard / fmxmlsnippet | `agent/scripts/` or `agent/sandbox/` | Clean, flat `<Step>` elements inside `<fmxmlsnippet type="FMObjectList">` | **Yes** — this is the output format |

## Refactoring workflow

When applying optimizations or refactoring an existing script:

1. **Find the fmxmlsnippet version** — check `agent/scripts/` for a pre-existing fmxmlsnippet of the script. If one exists, copy it directly into `agent/sandbox/` as the base. Do NOT use the `xml_parsed/scripts/` version as a base.
2. **If no fmxmlsnippet version exists**, the xml_parsed version must first be translated into fmxmlsnippet format. A dedicated translation script (`agent/scripts/fm_xml_to_snippet.py`) should be used for this if available. Do not attempt a manual full-script conversion.
3. **Apply only the targeted changes** — add, remove, or edit only the specific `<Step>` elements identified in the review. All unchanged steps remain verbatim.
4. **Follow `AGENTS.md` for all output rules** — use `snippet_examples` only to verify the structure of new or modified step types. Do not re-validate every existing step.
5. **Run the validator**: `python3 agent/scripts/validate_snippet.py agent/sandbox/<script_name>` and fix any errors before presenting the result.
