---
name: menu-lookup
description: Locate a specific FileMaker custom menu or menu set in `agent/xml_parsed/custom_menus/` or `agent/xml_parsed/custom_menu_sets/`. Extracts the real UUIDs required before creating or modifying any menu XML. Use when the user asks to create, modify, review, or look up a custom menu or menu set by name or ID.
---

# Menu Lookup

This skill locates a FileMaker custom menu or menu set in the parsed XML export and surfaces the critical UUIDs required before any menu XML can be created or modified. Without the correct UUIDs, FileMaker silently ignores paste operations.

It resolves using either:
- A **menu name** (exact/contains/fuzzy match), or
- A **menu ID** (numeric, from the menu set's `<CustomMenuReference id="N">`)

## Multi-solution structure

`xml_parsed/` is organized with **one subfolder per solution file** (e.g., `xml_parsed/custom_menus/Invoice Solution/`). A developer may work across multiple solutions or multiple files within a solution (data separation model). Always use `ls` via Bash — not Glob — to list subfolders, because solution names often contain spaces that break Glob patterns.

## Quick start

When invoked:

1. **Determine the solution subfolder** — list subdirectories under `agent/xml_parsed/custom_menus/` (and/or `custom_menu_sets/`) using Bash `ls`.
   - If only one subfolder exists, use it automatically (note the name in the report).
   - If multiple subfolders exist, use `AskUserQuestion` to ask which solution the developer is working with before proceeding.
2. Determine whether the target is a **CustomMenu** (individual menu) or **CustomMenuSet** (the container assigned to a layout).
3. Check `agent/sandbox/` for any in-progress XML for this menu.
4. List all menu files in the chosen solution subfolder using Bash `ls`.
   - Apply the matching workflow (below) against the file list.
   - If the match is ambiguous (multiple plausible candidates or no match), use `AskUserQuestion` to present the candidates and ask which menu to work with.
5. Read the matched file and extract the **critical UUIDs** (see below).
6. Output the **Menu match report**.
7. Use `AskUserQuestion` to confirm before proceeding.

**If `agent/xml_parsed/custom_menus/` or `agent/xml_parsed/custom_menu_sets/` does not exist or is empty**, report that explicitly and stop. Do not guess. Instruct the user to export menus from FileMaker first.

---

## Critical UUIDs — why they matter

FileMaker uses UUIDs to match pasted XML against existing objects in the solution. If either UUID is wrong or made up, the paste silently does nothing.

| UUID | Location in XML | Purpose |
|---|---|---|
| **CustomMenuCatalog UUID** | `<CustomMenuCatalog> > <UUID>` | Identifies the solution's menu catalog |
| **CustomMenu UUID** | `<CustomMenu> > <UUID>` | Identifies the specific menu to update |
| **CustomMenuSetCatalog UUID** | `<CustomMenuSetCatalog> > <UUID>` | Identifies the solution's menu set catalog |
| **CustomMenuSet UUID** | `<CustomMenuSet> > <UUID>` | Identifies the specific menu set to update |

Always read these directly from `xml_parsed/` — never invent them.

---

## Matching workflow

Follow this order and stop at the first **high confidence** match:

1. **ID match** (highest confidence) — menu `id` attribute matches (e.g. `<CustomMenu name="Format" id="31">`)
2. **Exact name match** (case-insensitive)
3. **Contains match** (all tokens present in candidate name)
4. **Fuzzy match** (rank candidates; return top 3–5)

---

## Menu match report (always include)

- **Selected menu**
  - Name: `<menu name>`
  - ID: `<id or unknown>`
  - Type: CustomMenu / CustomMenuSet
  - Confidence: High / Medium / Low (reason)

- **Paths found**
  - Source XML: `<path in xml_parsed/custom_menus/ or custom_menu_sets/, or "not found">`
  - In-progress sandbox: `<path in agent/sandbox/, or "not found">`

- **Extracted UUIDs**
  - Catalog UUID: `<UUID>`
  - Menu/Set UUID: `<UUID>`
  - Menu item count: `<N from MenuItemList membercount>`

- **Alternates (if any)**
  - Up to 3–5 other candidates (name + ID + path)

---

## Confirmation step

After the report, **always** use `AskQuestion` to confirm before proceeding.

- **Prompt**: `"Is this the correct menu? — Format (ID: 31) in xml_parsed/custom_menus/"`
- **Options**: `yes` / `no — let me clarify`

---

## Handoff: creating or modifying menu XML

Once confirmed:

### Modifying an existing menu

1. Use the source XML from `xml_parsed/custom_menus/` as the base — copy to `agent/sandbox/` if not already there.
2. Apply the requested changes following the structure in `agent/docs/CUSTOM_MENUS.md`.
3. Keep both the `CustomMenuCatalog UUID` and `CustomMenu UUID` from the original — do not regenerate them.
4. Write to clipboard: `python agent/scripts/clipboard.py write agent/sandbox/<menu>.xml`
5. In FileMaker: open Manage > Custom Menus, select the target menu, paste.

### Creating a new menu item block for an existing menu

1. Confirm the menu's real UUIDs from the match report above.
2. Build new `<CustomMenuItem>` elements using the patterns in `agent/docs/CUSTOM_MENUS.md`.
3. `CustomMenuItem UUID` and `hash` values can be placeholder — FileMaker reassigns on paste.
4. Increment `MenuItemList membercount` to match the new total.
5. Write and paste as above.

### Creating a brand-new menu (no existing XML)

The `xml_parsed/` export for this menu won't exist yet. The correct workflow is:

1. In FileMaker, create the empty menu in Manage > Custom Menus.
2. Copy it from FileMaker and save: `python agent/scripts/clipboard.py read agent/sandbox/<menu>-original.xml`
3. Use this file as the base — it contains the real UUIDs.
4. Build the menu XML from there following `agent/docs/CUSTOM_MENUS.md`.

---

## Key reference

Full XML patterns, shortcut modifier values, `<Override>` rules, `<Base>` element behavior, and the `ut16` clipboard format are documented in:

`agent/docs/CUSTOM_MENUS.md`

---

## Examples

### Example 1 — Single solution, unambiguous match

User: "Add a Sort Lines item to the Format menu"

- `ls agent/xml_parsed/custom_menus/` → one subfolder: `Invoice Solution`
- `ls "agent/xml_parsed/custom_menus/Invoice Solution/"` → find "agentic-fm — Format - ID 40.xml" (exact match)
- Read file, extract UUIDs, report match, confirm with `AskUserQuestion`.
- On confirmation: add the new `<CustomMenuItem>` block, write to clipboard.

### Example 2 — Multiple solutions present

User: "Look up the Format menu"

- `ls agent/xml_parsed/custom_menus/` → two subfolders: `Invoice Solution`, `Data.fmp12`
- `AskUserQuestion`: "Multiple solution files found: Invoice Solution, Data.fmp12 — which are you working with?"
- User selects → proceed with that subfolder.

### Example 3 — Ambiguous menu name

User: "Open the Format menu"

- `ls "agent/xml_parsed/custom_menus/Invoice Solution/"` → finds "agentic-fm — Format - ID 40.xml", "Format 2 - ID 34.xml", "Format 3 - ID 37.xml"
- `AskUserQuestion`: "Multiple Format menus found — which one? agentic-fm — Format (ID 40) / Format 2 (ID 34) / Format 3 (ID 37)"
- User selects → read file, extract UUIDs, report, confirm.

### Example 4 — New menu with no existing XML

User: "Create a View menu"

- `ls "agent/xml_parsed/custom_menus/Invoice Solution/"` → no View menu found.
- Report that the menu hasn't been exported yet.
- Instruct: create the empty menu in FileMaker, copy it, then run `clipboard.py read` to capture the real UUIDs before generation begins.
