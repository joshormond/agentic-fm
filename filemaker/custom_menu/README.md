# Custom Menu Integration

This folder contains the files needed to add an editor-aware custom menu set to a FileMaker layout hosting the agentic-fm web viewer. This integration is **optional** — it adds five menus (File, Edit, Selection, Format, View) populated with editor keyboard shortcuts and actions that are routed through a bridge script to the Monaco editor.

| File | Type | Description |
|---|---|---|
| `Agentic-fm Menu-script.xml` | fmxmlsnippet | Bridge script that receives a menu action string as `Get(ScriptParameter)` and forwards it to the web viewer |
| `custom_menus.xml` | FMObjectTransfer (ut16) | All 5 custom menus with their items |
| `custom_menu_set.xml` | FMObjectTransfer (ut16) | The `agentic-fm` menu set referencing the 5 menus |

---

## How it works

Each menu item calls a single bridge script — **Agentic-fm Menu** — passing a Monaco action ID as its parameter (e.g. `"editor.action.commentLine"` or `"agfm.newScript"`). The script passes that action through to the `agentic-fm` web viewer object on the layout via `Perform JavaScript in Web Viewer`.

The web viewer object on the target layout **must be named `agentic-fm`** for the bridge script to reach it.

---

## Prerequisites

- The agentic-fm web viewer is embedded on a layout with the object name `agentic-fm`
- The main agentic-fm scripts are already installed (see `filemaker/README.md`)
- The Explode XML script has been run at least once so `agent/xml_parsed/` is populated

---

## Integration steps

Because FileMaker custom menus use solution-specific UUIDs and script IDs, the XML files in this folder cannot be pasted directly — an agent must substitute the correct values for your solution first.

### 1. Install the bridge script

Load the script onto the clipboard and paste it into your Script Workspace:

```bash
source .venv/bin/activate
python agent/scripts/clipboard.py write filemaker/custom_menu/Agentic-fm Menu-script.xml
```

Switch to FileMaker, open **Scripts > Script Workspace**, click in the script list, and press **⌘V**. The **Agentic-fm Menu** script will appear.

**Note the script ID FileMaker assigns to it** — you will need this in step 4. You can find it by running the Explode XML script (which populates `agent/xml_parsed/`) and then checking `agent/context/scripts.index`:

```bash
grep "Agentic-fm Menu" agent/context/scripts.index
```

### 2. Create placeholder custom menus in FileMaker

FileMaker must assign UUIDs to the menus before their contents can be pasted. In FileMaker, go to **File > Manage > Custom Menus** and create five empty custom menus with **exactly these names**:

- `agentic-fm — File`
- `agentic-fm — Edit`
- `agentic-fm — Selection`
- `agentic-fm — Format`
- `agentic-fm — View`

Name spelling and dashes matter — the agent matches by name when looking up UUIDs.

### 3. Create the custom menu set

Still in Manage > Custom Menus, create a new custom menu set named **`agentic-fm`**. Add the five menus to it in this order:

1. agentic-fm — File
2. agentic-fm — Edit
3. agentic-fm — Selection
4. agentic-fm — Format
5. agentic-fm — View

Click **OK** to save and close.

### 4. Run Explode XML

Run the **Explode XML** script (or `fmparse.sh` from the terminal) to export the updated solution XML. This writes the new menus and menu set — including their real UUIDs — to `agent/xml_parsed/custom_menus/` and `agent/xml_parsed/custom_menu_sets/`.

### 5. Ask the agent to update the menu XML

Give the agent a prompt like:

> "Update `filemaker/custom_menu/custom_menus.xml` to use script ID `<your_script_id>` for the Agentic-fm Menu script, substituting real UUIDs from the exported menus in `agent/xml_parsed/custom_menus/`. Write the result to `agent/sandbox/custom_menus.xml` and load it onto the clipboard."

The agent will use the `menu-lookup` skill to locate each menu's real UUID, substitute your script ID for all `<Script id="271">` references, and run `clipboard.py write` when done.

### 6. Paste the custom menus

In FileMaker, open **File > Manage > Custom Menus**. Select the first menu in the list (`agentic-fm — File`), then press **⌘V**. Repeat for each of the five menus — FileMaker matches by UUID and populates each menu with its items.

### 7. Assign the menu set to the layout

Switch to the layout that hosts the web viewer. Enter **Layout mode**, open **Layouts > Layout Setup**, and under **Menu Set** choose **agentic-fm**. Save the layout.

---

## Troubleshooting

**Paste does nothing** — The UUID in the XML does not match the solution. Make sure step 4 (Explode XML) ran after you created the menus in step 2, and that the agent read the UUIDs from `agent/xml_parsed/custom_menus/` rather than from this folder.

**Menu actions have no effect** — Confirm the web viewer object on the layout is named exactly `agentic-fm`. Check that the bridge script is installed and its name is **Agentic-fm Menu**.

**Wrong script called** — The `<Script id="...">` in `custom_menus.xml` still references the source solution's ID (271). Repeat step 5 with the correct ID for your solution.

---

For full technical details on the custom menu clipboard format, UUID requirements, and `<Override>` attribute rules, see `agent/docs/CUSTOM_MENUS.md`.
