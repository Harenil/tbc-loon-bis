#!/usr/bin/env python3
"""
parse_loon_bis.py

Extract all BIS item data from LoonBestInSlot-tbc-v1.0.9.zip and output as CSV.

Usage:
    python3 parse_loon_bis.py
"""

import csv
import io
import os
import re
import zipfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.environ.get(
    "LOON_BIS_ZIP",
    os.path.join(REPO_ROOT, "LoonBestInSlot-tbc-v1.0.9.zip"),
)
OUTPUT_CSV = os.path.join(REPO_ROOT, "loonbestinslot_items.csv")

# TBC 5-man dungeons (exact location names used in SourceLocation)
TBC_DUNGEONS = {
    "Hellfire Ramparts",
    "The Blood Furnace",
    "The Shattered Halls",
    "The Slave Pens",
    "The Underbog",
    "The Steamvault",
    "Mana-Tombs",
    "Mana Tombs",
    "Auchenai Crypts",
    "Sethekk Halls",
    "Shadow Labyrinth",
    "The Mechanar",
    "The Botanica",
    "The Arcatraz",
    "Old Hillsbrad Foothills",
    "The Black Morass",
    "Magisters' Terrace",
    "Auchindoun",
}

# Markers indicating a heroic dungeon variant
HEROIC_MARKERS = ("(H)", "(Heroic)", "(HC)", " HC", " Heroic")


def get_dungeon_difficulty(zone: str) -> str:
    """Return 'Heroic', 'Normal', or '' based on zone name."""
    if not zone:
        return ""
    for marker in HEROIC_MARKERS:
        if marker in zone:
            return "Heroic"
    # Strip trailing difficulty markers to get the base zone name
    base_zone = zone
    for marker in HEROIC_MARKERS:
        base_zone = base_zone.replace(marker, "").strip()
    # Also strip "(Fire Event)" and similar
    base_zone = re.sub(r"\s*\([^)]*\)\s*$", "", base_zone).strip()
    if base_zone in TBC_DUNGEONS:
        return "Normal"
    return ""


def extract_lbis_string(raw: str) -> str:
    """
    Extract the English string value from a Lua expression like:
      LBIS.L["Some Name"]
      LBIS.L["A"].." & "..LBIS.L["B"]
      "literal string"
      123
    Returns the resolved English string.
    """
    raw = raw.strip()
    if not raw:
        return ""
    # Handle concatenation: split on '.."..."..', collect all LBIS.L["..."] parts
    parts = re.findall(r'LBIS\.L\["([^"]+)"\]', raw)
    if parts:
        # Join parts preserving the separator text from the concatenation
        result = parts[0]
        seps = re.findall(r'\.\."([^"]*)"\.\.|\.\."\s*([^"]*)\s*"\s*$', raw)
        flat_seps = [s[0] or s[1] for s in seps]
        for i, part in enumerate(parts[1:]):
            sep = flat_seps[i] if i < len(flat_seps) else " & "
            result += sep + part
        return result
    # Plain quoted string
    m = re.match(r'^"([^"]*)"$', raw)
    if m:
        return m.group(1)
    # Numeric value (e.g. recipe ID as SourceLocation)
    if re.match(r'^\d+$', raw):
        return raw
    return raw


def parse_item_sources(lua_text: str) -> dict:
    """
    Parse LBIS.ItemSources table from ItemSources.lua.
    Returns dict: item_id (int) -> {Name, SourceType, Source, SourceLocation, SourceNumber, SourceFaction}
    """
    items = {}
    # Match each entry: [ID] = { ... }
    entry_pattern = re.compile(
        r'\[(\d+)\]\s*=\s*\{([^}]+)\}', re.DOTALL
    )
    for m in entry_pattern.finditer(lua_text):
        item_id = int(m.group(1))
        body = m.group(2)
        fields = {}
        for fm in re.finditer(
            r'(\w+)\s*=\s*((?:LBIS\.L\["[^"]*"\](?:\s*\.\.\s*"[^"]*"\s*\.\.\s*LBIS\.L\["[^"]*"\])*\s*(?:\.\.\s*LBIS\.L\["[^"]*"\])*)|"[^"]*"|\d+)',
            body
        ):
            key = fm.group(1)
            val_raw = fm.group(2).strip()
            fields[key] = extract_lbis_string(val_raw)
        items[item_id] = fields
    return items


def parse_guide_file(lua_text: str) -> list:
    """
    Parse a Guide Lua file.
    Returns list of dicts: {item_id, slot, bis, class_, spec, phase}
    """
    rows = []

    # Parse RegisterSpec calls: local specN = LBIS:RegisterSpec(LBIS.L["Class"], LBIS.L["Spec"], "Phase")
    spec_map = {}  # variable name -> {class_, spec, phase}
    for m in re.finditer(
        r'local\s+(spec\w+)\s*=\s*LBIS:RegisterSpec\(\s*LBIS\.L\["([^"]+)"\]\s*,\s*LBIS\.L\["([^"]+)"\]\s*,\s*"([^"]+)"\s*\)',
        lua_text
    ):
        var_name, class_, spec, phase = m.group(1), m.group(2), m.group(3), m.group(4)
        spec_map[var_name] = {"class_": class_, "spec": spec, "phase": phase}

    # Parse AddItem calls: LBIS:AddItem(specN, "ItemId", LBIS.L["Slot"], "BIS")
    for m in re.finditer(
        r'LBIS:AddItem\(\s*(\w+)\s*,\s*"(\d+)"\s*,\s*LBIS\.L\["([^"]+)"\]\s*,\s*"([^"]+)"\s*\)',
        lua_text
    ):
        var_name = m.group(1)
        item_id = int(m.group(2))
        slot = m.group(3)
        bis = m.group(4)
        if var_name in spec_map:
            spec_info = spec_map[var_name]
            rows.append({
                "item_id": item_id,
                "slot": slot,
                "bis": bis,
                "class_": spec_info["class_"],
                "spec": spec_info["spec"],
                "phase": spec_info["phase"],
            })

    return rows


def format_phase(phase: str) -> str:
    """Convert phase number to display string (0 -> 'P')."""
    return phase.replace("0", "P")


def format_bis_status(bis: str, phase: str) -> str:
    """Format the BIS Status/arguments column: '{bis} {phase_display}'."""
    phase_display = format_phase(phase)
    return f"{bis} {phase_display}"


def main():
    print(f"Reading zip: {ZIP_PATH}")
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        file_names = zf.namelist()

        # Read ItemSources.lua
        item_sources_path = next(
            (f for f in file_names if f.endswith("DB/ItemSources.lua")), None
        )
        if not item_sources_path:
            raise FileNotFoundError("ItemSources.lua not found in zip")
        item_sources_text = zf.read(item_sources_path).decode("utf-8", errors="replace")

        # Read Guide files
        guide_paths = sorted(
            f for f in file_names if "/Guides/" in f and f.endswith(".lua")
            and not f.endswith("Guides.lua")
        )
        guide_texts = {
            os.path.basename(p): zf.read(p).decode("utf-8", errors="replace")
            for p in guide_paths
        }

    print(f"Parsing ItemSources.lua...")
    item_sources = parse_item_sources(item_sources_text)
    print(f"  Found {len(item_sources)} items in ItemSources")

    print(f"Parsing {len(guide_texts)} guide files...")
    all_rows = []
    for guide_name, guide_text in sorted(guide_texts.items()):
        rows = parse_guide_file(guide_text)
        print(f"  {guide_name}: {len(rows)} item assignments")
        all_rows.extend(rows)
    print(f"Total item assignments: {len(all_rows)}")

    # CSV columns
    fieldnames = [
        "Id", "Name", "Quality", "Slot", "Type", "SubType", "Texture",
        "Source", "Zone", "Dungeon Difficulty", "Phase", "Class", "Spec",
        "BIS Status/arguments", "Link",
        "SourceType", "SourceNumber", "SourceFaction",
    ]

    print(f"Writing CSV to {OUTPUT_CSV}...")
    written = 0
    skipped = 0
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for row in all_rows:
            item_id = row["item_id"]
            src = item_sources.get(item_id, {})
            name = src.get("Name", "")

            # Skip items missing Id or Name
            if not item_id or not name:
                skipped += 1
                continue

            zone = src.get("SourceLocation", "")
            dungeon_diff = get_dungeon_difficulty(zone)

            writer.writerow({
                "Id": item_id,
                "Name": name,
                "Quality": "",
                "Slot": row["slot"],
                "Type": "",
                "SubType": "",
                "Texture": "",
                "Source": src.get("Source", ""),
                "Zone": zone,
                "Dungeon Difficulty": dungeon_diff,
                "Phase": format_phase(row["phase"]),
                "Class": row["class_"],
                "Spec": row["spec"],
                "BIS Status/arguments": format_bis_status(row["bis"], row["phase"]),
                "Link": f"https://wowhead.com/item={item_id}",
                "SourceType": src.get("SourceType", ""),
                "SourceNumber": src.get("SourceNumber", ""),
                "SourceFaction": src.get("SourceFaction", ""),
            })
            written += 1

    print(f"Done. Written {written} rows, skipped {skipped} (missing Id or Name).")
    print(f"Output: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
