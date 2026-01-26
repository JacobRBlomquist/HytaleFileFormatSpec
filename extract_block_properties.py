#!/usr/bin/env python3
"""
Extract block rendering properties from Hytale assets
Creates a simplified JSON file with just TintUp, BiomeTintUp, and ParticleColor
"""
import json
from pathlib import Path


def extract_block_properties(assets_path):
    """Extract rendering properties from all block items"""
    assets_path = Path(assets_path)
    items_path = assets_path / "Server" / "Item" / "Items"

    block_properties = {}

    # Walk through all JSON files in Items directory
    for json_file in items_path.rglob("*.json"):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Check if this item has BlockType data
            if "BlockType" not in data:
                continue

            block_type = data["BlockType"]

            # Extract the block name from the filename
            block_name = json_file.stem

            # Extract the properties we need for map rendering
            # Check for both "Tint" and "TintUp" (Tint is more common)
            tint = block_type.get("Tint") or block_type.get("TintUp") or []

            properties = {
                "TintUp": tint,
                "BiomeTintUp": block_type.get("BiomeTintUp", 100 if tint else 0),  # Default to 100% if tinted
                "ParticleColor": block_type.get("ParticleColor", None)
            }

            block_properties[block_name] = properties

        except (json.JSONDecodeError, KeyError) as e:
            # Skip files that aren't valid JSON or don't have expected structure
            continue

    return block_properties


def main():
    assets_path = Path("Assets")

    if not assets_path.exists():
        print(f"Error: Assets directory not found at {assets_path}")
        return

    print("Extracting block properties from Assets...")
    block_properties = extract_block_properties(assets_path)

    print(f"Found {len(block_properties)} blocks with BlockType data")

    # Save to JSON file
    output_file = "block_properties.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(block_properties, f, indent=2)

    print(f"Saved block properties to {output_file}")

    # Print some examples
    print("\nExample blocks:")
    for i, (name, props) in enumerate(list(block_properties.items())[:5]):
        print(f"  {name}:")
        print(f"    TintUp: {props['TintUp']}")
        print(f"    BiomeTintUp: {props['BiomeTintUp']}")
        print(f"    ParticleColor: {props['ParticleColor']}")


if __name__ == "__main__":
    main()
