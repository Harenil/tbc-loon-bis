#!/usr/bin/env python3
"""
Extract item data from LoonBestInSlot-tbc-v1.0.9.zip and generate a CSV.

Usage:
    python extract_items.py

Outputs:
    loonbestinslot_items.csv in the current directory.
"""

import csv
import os
import re
import zipfile

ZIP_PATH = "LoonBestInSlot-tbc-v1.0.9.zip"
OUTPUT_CSV = "loonbestinslot_items.csv"

# TBC 5-man dungeon zones (normal difficulty — no heroic marker in name)
TBC_DUNGEONS = {
    "Hellfire Ramparts",
    "The Blood Furnace",
    "The Shattered Halls",
    "The Slave Pens",
    "The Underbog",
    "The Steamvault",
    "Mana Tombs",
    "Mana-Tombs",
    "Auchenai Crypts",
    "Sethekk Halls",
    "Shadow Labyrinth",
    "The Mechanar",
    "The Botanica",
    "The Arcatraz",
    "The Black Morass",
    "Old Hillsbrad Foothills",
    "Magisters' Terrace",
}


def extract_lua_string(val):
    """
    Extract the English string from a Lua expression like:
      LBIS.L["Some Text"]
      "Some Text"
      LBIS.L["A"].." & "..LBIS.L["B"]
    Returns the plain string value.
    """
    # Replace all LBIS.L["X"] occurrences with X
    result = re.sub(r'LBIS\.L\["([^"]+)"\]', r'\1', val)
    # Replace Lua concat ".." and surrounding spaces/quotes with the literal & separators
    result = re.sub(r'"\s*\.\.\s*"', '', result)
    result = re.sub(r'\s*\.\.\s*', '', result)
    # Strip remaining surrounding quotes
    result = result.strip().strip('"')
    return result


def parse_item_sources(content):
    """
    Parse LBIS.ItemSources table from ItemSources.lua content.
    Returns dict: {item_id (int): {Name, SourceType, Source, SourceNumber, SourceLocation, SourceFaction}}
    """
    items = {}
    # Match each table row: [id] = { ... }
    row_pattern = re.compile(
        r'\[(\d+)\]\s*=\s*\{([^}]+)\}', re.DOTALL
    )
    field_pattern = re.compile(
        r'(\w+)\s*=\s*(LBIS\.L\["[^"]*"\](?:\s*\.\.\s*(?:"[^"]*"\s*\.\.\s*)?LBIS\.L\["[^"]*"\])*|"[^"]*")',
    )
    for row_match in row_pattern.finditer(content):
        item_id = int(row_match.group(1))
        body = row_match.group(2)
        fields = {}
        for f in field_pattern.finditer(body):
            key = f.group(1)
            raw_val = f.group(2)
            fields[key] = extract_lua_string(raw_val)
        if "Name" in fields:
            items[item_id] = fields
    return items


def parse_guide_file(content):
    """
    Parse a Guide Lua file to extract spec registrations and AddItem calls.

    Returns list of dicts:
      {item_id, slot, bis, class_name, spec_name, phase}
    """
    # Map local variable name -> (class_name, spec_name, phase)
    spec_vars = {}

    reg_pattern = re.compile(
        r'local\s+(spec\w+)\s*=\s*LBIS:RegisterSpec\s*\('
        r'\s*LBIS\.L\["([^"]+)"\]\s*,\s*LBIS\.L\["([^"]+)"\]\s*,\s*"([^"]+)"\s*\)'
    )
    for m in reg_pattern.finditer(content):
        var_name = m.group(1)
        class_name = m.group(2)
        spec_name = m.group(3)
        phase = m.group(4)
        spec_vars[var_name] = (class_name, spec_name, phase)

    add_item_pattern = re.compile(
        r'LBIS:AddItem\s*\(\s*(\w+)\s*,\s*"(\d+)"\s*,\s*LBIS\.L\["([^"]+)"\]\s*,\s*"([^"]+)"\s*\)'
    )
    entries = []
    for m in add_item_pattern.finditer(content):
        var_name = m.group(1)
        item_id = int(m.group(2))
        slot = m.group(3)
        bis = m.group(4)
        if var_name in spec_vars:
            class_name, spec_name, phase = spec_vars[var_name]
            entries.append({
                "item_id": item_id,
                "slot": slot,
                "bis": bis,
                "class_name": class_name,
                "spec_name": spec_name,
                "phase": phase,
            })
    return entries


def get_dungeon_difficulty(source_type, source_location):
    """
    Determine dungeon difficulty for an item.
    Returns "Heroic", "Normal", or "" (blank).
    """
    loc = source_location or ""
    # Heroic dungeons explicitly marked
    if "(Heroic)" in loc or "(H)" in loc:
        return "Heroic"
    # Check if it's a known TBC dungeon (non-heroic)
    # Strip trailing whitespace for comparison
    loc_stripped = loc.strip()
    if loc_stripped in TBC_DUNGEONS:
        return "Normal"
    return ""


def main():
    if not os.path.exists(ZIP_PATH):
        raise FileNotFoundError(f"Zip file not found: {ZIP_PATH}")

    # Read all relevant files from zip
    lua_files = {}
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        for name in zf.namelist():
            if name.endswith(".lua"):
                with zf.open(name) as f:
                    lua_files[name] = f.read().decode("utf-8", errors="replace")

    # Parse ItemSources
    item_sources_key = next(
        (k for k in lua_files if k.endswith("DB/ItemSources.lua")), None
    )
    if item_sources_key is None:
        raise RuntimeError("Could not find DB/ItemSources.lua in zip")
    item_sources = parse_item_sources(lua_files[item_sources_key])

    # Parse all guide files
    all_entries = []
    guide_keys = sorted(k for k in lua_files if "/Guides/" in k and k.endswith(".lua"))
    for key in guide_keys:
        entries = parse_guide_file(lua_files[key])
        all_entries.extend(entries)

    # Build CSV rows
    csv_columns = [
        "Id", "Name", "Quality", "Slot", "Type", "SubType", "Texture",
        "Source", "Zone", "Dungeon Difficulty", "Phase", "Class", "Spec",
        "BIS Status/arguments", "Link",
        "SourceType", "SourceNumber", "SourceFaction",
    ]

    rows = []
    for entry in all_entries:
        item_id = entry["item_id"]
        src = item_sources.get(item_id, {})
        name = src.get("Name", "")
        if item_id is None or not name:
            continue

        source_type = src.get("SourceType", "")
        source = src.get("Source", "")
        zone = src.get("SourceLocation", "")
        source_number = src.get("SourceNumber", "")
        source_faction = src.get("SourceFaction", "")

        dungeon_difficulty = get_dungeon_difficulty(source_type, zone)

        row = {
            "Id": item_id,
            "Name": name,
            "Quality": "",
            "Slot": entry["slot"],
            "Type": "",
            "SubType": "",
            "Texture": "",
            "Source": source,
            "Zone": zone,
            "Dungeon Difficulty": dungeon_difficulty,
            "Phase": entry["phase"],
            "Class": entry["class_name"],
            "Spec": entry["spec_name"],
            "BIS Status/arguments": entry["bis"],
            "Link": f"https://wowhead.com/item={item_id}",
            "SourceType": source_type,
            "SourceNumber": source_number,
            "SourceFaction": source_faction,
        }
        rows.append(row)

    # Write CSV
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Written {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
