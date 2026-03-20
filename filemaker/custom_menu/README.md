# Custom Menu Integration

This folder contains the files needed to add an editor-aware custom menu set to a FileMaker layout hosting the agentic-fm web viewer. This integration is **optional** — it adds five menus (File, Edit, Selection, Format, View) populated with editor keyboard shortcuts and actions that are routed through a bridge script to the Monaco editor.

| File                         | Type                    | Description                                                                                                  |
| ---------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------ |
| `Agentic-fm Menu-script.xml` | fmxmlsnippet            | Bridge script that receives a menu action string as `Get(ScriptParameter)` and forwards it to the web viewer |
| `custom_menus.xml`           | FMObjectTransfer (ut16) | All 5 custom menus with their items                                                                          |
| `custom_menu_set.xml`        | FMObjectTransfer (ut16) | The `agentic-fm` menu set referencing the 5 menus                                                            |

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
python3 agent/scripts/clipboard.py write filemaker/custom_menu/Agentic-fm Menu-script.xml
```

Switch to FileMaker, open **Scripts > Script Workspace**, click in the script list, and press **⌘V**. The **Agentic-fm Menu** script will appear.

**Note the script ID FileMaker assigns to it** — you will need this in step 4. You can find it by running the Explode XML script (which populates `agent/xml_parsed/`) and then checking your solution's scripts index:

```bash
grep "Agentic-fm Menu" "agent/context/agentic-fm/scripts.index"
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

### 4. Capture snapshots

With the placeholder menus and menu set still selected in FileMaker:

1. In **Manage > Custom Menus**, select **all five menus**, copy them (⌘C), then run:

```bash
python3 agent/scripts/clipboard.py read agent/sandbox/custom_menus.xml
```

2. Select the **agentic-fm** menu set, copy it (⌘C), then run:

```bash
python3 agent/scripts/clipboard.py read agent/sandbox/custom_menu_set.xml
```

These snapshot files capture the solution-specific catalog UUIDs that FileMaker requires for paste operations.

### 5. Run Explode XML

Run the **Explode XML** script (or `fmparse.sh` from the terminal) to export the updated solution XML. This writes the new menus and menu set — including their real UUIDs — to `agent/xml_parsed/custom_menus/` and `agent/xml_parsed/custom_menu_sets/`.

### 6. Run the install script

```bash
python3 agent/scripts/install_menus.py
```

The script auto-reads UUIDs from `xml_parsed/`, looks up the script ID from `context/{solution}/scripts.index`, builds the populated XML, writes it to `agent/sandbox/custom_menus.xml`, and loads it onto the clipboard.

### 7. Paste the custom menus

In FileMaker, open **File > Manage > Custom Menus**. Select the first menu in the list (`agentic-fm — File`), then press **⌘V**. Repeat for each of the five menus — FileMaker matches by UUID and populates each menu with its items.

### 8. Load and paste the menu set

```bash
python3 agent/scripts/install_menus.py --set
```

In FileMaker, select the **agentic-fm** menu set and press **⌘V**.

### 9. Assign the menu set to the layout

Switch to the layout that hosts the web viewer. Enter **Layout mode**, open **Layouts > Layout Setup**, and under **Menu Set** choose **agentic-fm**. Save the layout.

---

## Troubleshooting

**Paste does nothing** — The UUID in the XML does not match the solution. Make sure step 4 (Explode XML) ran after you created the menus in step 2, and that the agent read the UUIDs from `agent/xml_parsed/custom_menus/` rather than from this folder.

**Menu actions have no effect** — Confirm the web viewer object on the layout is named exactly `agentic-fm`. Check that the bridge script is installed and its name is **Agentic-fm Menu**.

**Wrong script called** — The `<Script id="...">` in `custom_menus.xml` still references the source solution's ID (271). Repeat step 5 with the correct ID for your solution.

---

For full technical details on the custom menu clipboard format, UUID requirements, and `<Override>` attribute rules, see `agent/docs/CUSTOM_MENUS.md`.
