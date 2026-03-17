#!/usr/bin/env python3
"""
deploy.py - Pluggable deployment module for agentic-fm.

Loads a validated fmxmlsnippet XML file to the FileMaker clipboard and
optionally triggers an automated paste into the Script Workspace.

Tier 1 (universal):  companion /clipboard → developer pastes manually
Tier 2 (MBS):        companion /clipboard + /trigger → Agentic-fm Paste auto-pastes
Tier 3 (MBS + AS):   companion /trigger creates placeholder → then Tier 2

Usage (CLI):
    python3 agent/scripts/deploy.py <xml_path> [target_script] [--tier N]

Usage (module):
    from deploy import deploy
    result = deploy("agent/sandbox/MyScript.xml", target_script="My Script")

Result dict keys:
    success       — bool
    tier_used     — int (1, 2, or 3; may differ from requested if fallback)
    instructions  — str (Tier 1 and fallback cases — present to developer)
    message       — str (Tier 2/3 success — for logging)
    fallback_from — int (present when fell back from a higher tier)
    fallback_reason — str (why the fallback occurred)
    error         — str (present on failure)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "default_tier": 1,
    "auto_save": False,
    "fm_app_name": "FileMaker Pro",
    "companion_url": "http://local.hub:8765",
}


def _load_config() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(here, "..", "config", "automation.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return {**DEFAULT_CONFIG, **cfg}
    except (OSError, ValueError):
        return DEFAULT_CONFIG.copy()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: dict, timeout: int = 15) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except ValueError:
            return {"success": False, "error": f"HTTP {exc.code}: {raw}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Tier 1
# ---------------------------------------------------------------------------

def _tier1(xml: str, companion_url: str, target_script: str | None) -> dict:
    """Write XML to clipboard via companion, return paste instructions."""
    result = _post_json(f"{companion_url}/clipboard", {"xml": xml})
    if not result.get("success"):
        return {
            "success": False,
            "tier_used": 1,
            "error": result.get("error", "Clipboard write failed"),
        }

    if target_script:
        instructions = (
            f"Script loaded to clipboard.\n"
            f"  1. In FM Pro open '{target_script}' in Script Workspace\n"
            f"  2. Select all steps (⌘A)\n"
            f"  3. Paste (⌘V)"
        )
    else:
        instructions = (
            "Script loaded to clipboard.\n"
            "  Paste (⌘V) into the target script in Script Workspace."
        )

    return {"success": True, "tier_used": 1, "instructions": instructions}


# ---------------------------------------------------------------------------
# Tier 2
# ---------------------------------------------------------------------------

def _tier2(
    xml: str,
    companion_url: str,
    fm_app_name: str,
    target_script: str | None,
    auto_save: bool = False,
    select_all: bool = True,
) -> dict:
    """Load clipboard then trigger FM Pro to run Agentic-fm Paste via AppleScript."""
    # Step 1: load clipboard
    clip_result = _post_json(f"{companion_url}/clipboard", {"xml": xml})
    if not clip_result.get("success"):
        return {
            "success": False,
            "tier_used": 2,
            "error": clip_result.get("error", "Clipboard write failed"),
        }

    if not target_script:
        return {
            "success": True,
            "tier_used": 2,
            "instructions": (
                "Script loaded to clipboard. No target script specified — paste manually (⌘V)."
            ),
        }

    # Step 2: trigger FM Pro to run Agentic-fm Paste
    trigger_result = _post_json(
        f"{companion_url}/trigger",
        {
            "fm_app_name": fm_app_name,
            "script": "Agentic-fm Paste",
            "parameter": target_script,
            "auto_save": auto_save,
            "select_all": select_all,
        },
    )
    if not trigger_result.get("success"):
        # Fall back to Tier 1 instructions — clipboard is already loaded
        return {
            "success": True,
            "tier_used": 1,
            "fallback_from": 2,
            "fallback_reason": trigger_result.get("error", "Trigger failed"),
            "instructions": (
                f"Auto-paste unavailable — clipboard is loaded, paste manually.\n"
                f"  1. In FM Pro open '{target_script}' in Script Workspace\n"
                f"  2. Select all steps (⌘A)\n"
                f"  3. Paste (⌘V)"
            ),
        }

    mode = "replaced" if select_all else "appended to"
    return {
        "success": True,
        "tier_used": 2,
        "message": f"Script steps {mode} '{target_script}' via MBS.",
    }


# ---------------------------------------------------------------------------
# Tier 3
# ---------------------------------------------------------------------------

def _tier3(
    xml: str,
    companion_url: str,
    fm_app_name: str,
    target_script: str | None,
    auto_save: bool = False,
) -> dict:
    """Create and name a script placeholder via AppleScript, then paste inline.

    Loads XML to clipboard first, then runs a raw AppleScript on the host
    (synchronous — waits for completion):
      1. Open Script Workspace if not already open
      2. Cmd+N  → creates "New Script"
      3. Scripts menu → Rename Script → type target name → Return
      4. Cmd+S  → save (required before do script, or FM blocks with dialog)
      5. Cmd+A  → select all steps
      6. Cmd+V  → paste from clipboard (already loaded in step 0)
      7. Cmd+S  → save after paste (always — new scripts are always saved)

    Notes:
      - tell application uses fm_app_name (versioned, with em dash)
      - tell process uses the base name only ("FileMaker Pro") — System Events
        process names never include the version suffix
      - raw_applescript is synchronous; clipboard must be loaded before firing
      - paste is done inline via System Events Cmd+V, not via Agentic-fm Paste
    """
    if not target_script:
        return _tier2(xml, companion_url, fm_app_name, target_script, auto_save)

    # Step 0: load clipboard before firing the AppleScript
    clip_result = _post_json(f"{companion_url}/clipboard", {"xml": xml})
    if not clip_result.get("success"):
        return {
            "success": False,
            "tier_used": 3,
            "error": clip_result.get("error", "Clipboard write failed"),
        }

    def _esc(s: str) -> str:
        """Escape a string for embedding inside an AppleScript double-quoted string."""
        return s.replace("\\", "\\\\").replace('"', '\\"')

    # System Events process name — always the base app name without version suffix.
    # "FileMaker Pro — 22.0.4.406" → "FileMaker Pro"
    fm_process = fm_app_name.split(" \u2014 ")[0].strip()

    applescript = (
        f'tell application "{_esc(fm_app_name)}"\n'
        f'    activate\n'
        f'end tell\n'
        f'\n'
        f'delay 0.5\n'
        f'\n'
        f'tell application "System Events"\n'
        f'    tell process "{_esc(fm_process)}"\n'
        f'        try\n'
        f'            click menu item "Script Workspace..." of menu "Scripts" of menu bar 1\n'
        f'            delay 1.0\n'
        f'        end try\n'
        f'        keystroke "n" using {{command down}}\n'
        f'        delay 0.5\n'
        f'        click menu item "Rename Script" of menu "Scripts" of menu bar 1\n'
        f'        delay 1.0\n'
        f'        keystroke "{_esc(target_script)}"\n'
        f'        delay 0.2\n'
        f'        key code 36\n'
        f'        delay 0.5\n'
        f'        keystroke "s" using {{command down}}\n'
        f'        delay 0.3\n'
        f'        keystroke "a" using {{command down}}\n'
        f'        delay 0.2\n'
        f'        keystroke "v" using {{command down}}\n'
        f'        delay 0.5\n'
        f'        keystroke "s" using {{command down}}\n'
        f'        delay 0.3\n'
        f'    end tell\n'
        f'end tell\n'
    )

    create_result = _post_json(
        f"{companion_url}/trigger",
        {"raw_applescript": applescript},
    )
    if not create_result.get("success"):
        # Script creation failed — fall through to Tier 2 (paste into existing)
        # Clipboard is already loaded so Tier 2 can skip the clipboard step.
        tier2_result = _tier2(xml, companion_url, fm_app_name, target_script, auto_save)
        return {
            **tier2_result,
            "fallback_from": 3,
            "fallback_reason": create_result.get("error", "Script creation failed"),
        }

    return {
        "success": True,
        "tier_used": 3,
        "message": f"Script '{target_script}' created, steps pasted, and saved via Tier 3.",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def deploy(
    xml_path: str,
    target_script: str | None = None,
    tier: int | None = None,
    auto_save: bool | None = None,
    select_all: bool = True,
) -> dict:
    """
    Deploy a validated fmxmlsnippet XML file to FileMaker.

    Args:
        xml_path:      Path to the fmxmlsnippet XML file.
        target_script: Name of the script to paste into (Tier 2/3).
        tier:          Override the configured default tier (1, 2, or 3).
        auto_save:     Override the configured auto_save setting.

    Returns:
        Result dict — always contains 'success' and 'tier_used'.
        Tier 1 / fallback: also contains 'instructions' to show the developer.
        Tier 2/3 success: also contains 'message' for logging.
    """
    config = _load_config()
    effective_tier = tier if tier is not None else config.get("default_tier", 1)
    effective_auto_save = auto_save if auto_save is not None else bool(config.get("auto_save", False))
    companion_url = config.get("companion_url", "http://local.hub:8765").rstrip("/")
    fm_app_name = config.get("fm_app_name", "FileMaker Pro")

    try:
        with open(xml_path, "r", encoding="utf-8") as f:
            xml = f.read()
    except OSError as exc:
        return {"success": False, "error": f"Cannot read {xml_path}: {exc}"}

    if effective_tier == 3:
        return _tier3(xml, companion_url, fm_app_name, target_script, effective_auto_save)
    elif effective_tier == 2:
        return _tier2(xml, companion_url, fm_app_name, target_script, effective_auto_save, select_all)
    else:
        return _tier1(xml, companion_url, target_script)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Deploy a validated fmxmlsnippet XML file to FileMaker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("xml_path", help="Path to the fmxmlsnippet XML file")
    parser.add_argument(
        "target_script", nargs="?", help="Script name to paste into (Tier 2/3)"
    )
    parser.add_argument(
        "--tier", type=int, choices=[1, 2, 3], help="Override deployment tier"
    )
    parser.add_argument(
        "--auto-save", action="store_true", default=None, dest="auto_save",
        help="Auto-save the script after paste (Tier 2/3 only)"
    )
    parser.add_argument(
        "--no-auto-save", action="store_false", dest="auto_save",
        help="Do not auto-save after paste (overrides config)"
    )
    paste_group = parser.add_mutually_exclusive_group()
    paste_group.add_argument(
        "--replace", action="store_true", default=False,
        help="Replace all existing steps without prompting (Tier 2 only)"
    )
    paste_group.add_argument(
        "--append", action="store_true", default=False,
        help="Append after existing steps without prompting (Tier 2 only)"
    )
    args = parser.parse_args()

    # Tier 2 targeting an existing script is destructive — always confirm unless
    # --replace or --append bypasses the prompt explicitly.
    select_all = True
    effective_tier = args.tier or _load_config().get("default_tier", 1)
    if effective_tier == 2 and args.target_script:
        if args.append:
            select_all = False
        elif not args.replace:
            print(f"\nScript '{args.target_script}' will be modified.")
            print("  [r] Replace — select all existing steps and paste (destructive)")
            print("  [a] Append  — paste after existing steps")
            print("  [c] Cancel")
            try:
                choice = input("Choice [r/a/c]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                sys.exit(0)
            if choice == "c":
                print("Cancelled.")
                sys.exit(0)
            elif choice == "a":
                select_all = False

    result = deploy(args.xml_path, args.target_script, args.tier, args.auto_save, select_all)

    # Human-friendly output
    if result.get("instructions"):
        print(result["instructions"])
    elif result.get("message"):
        print(result["message"])
    elif result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)

    if result.get("fallback_from"):
        print(
            f"(Fell back from Tier {result['fallback_from']}: {result.get('fallback_reason', '')})",
            file=sys.stderr,
        )

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
