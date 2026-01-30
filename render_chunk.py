#!/usr/bin/env python3
"""
Simple chunk renderer - generates a top-down map image of a single chunk
"""
import sys
import struct
import math
import io
from pathlib import Path
sys.path.insert(0, "..")
import compression.zstd as zstd
import bson
from PIL import Image

# BASE_PATH = "SRV/universe/worlds/default/chunks"
BASE_PATH = "C:/Users/Jacob/AppData/Roaming/Hytale/UserData/Saves/2026-01-30/universe/worlds/default_world/chunks"
HEADER_LENGTH = 32

def read_chunk_data(chunk_x, chunk_z):
    """Read chunk from region file"""
    # Calculate region
    region_x = (chunk_x * 32) // 1024
    region_z = (chunk_z * 32) // 1024

    region_path = Path(f"{BASE_PATH}/{region_x}.{region_z}.region.bin")
    if not region_path.exists():
        print(f"Region file not found: {region_path}")
        return None

    with region_path.open("rb") as f:
        # Read header
        header = f.read(HEADER_LENGTH)
        magic, version, blob_count, segment_size = struct.unpack(">20sIII", header)

        # Get chunk location
        relative_x = (chunk_x * 32 // 32) % 32
        relative_z = (chunk_z * 32 // 32) % 32
        index_offset = (relative_x + relative_z * 32) * 4

        f.seek(HEADER_LENGTH + index_offset)
        segment = struct.unpack(">I", f.read(4))[0]

        if segment == 0:
            print(f"Chunk ({chunk_x}, {chunk_z}) not present")
            return None

        # Read chunk
        f.seek(segment * segment_size + HEADER_LENGTH)
        uncompressed_size, compressed_size = struct.unpack(">II", f.read(8))
        compressed_data = f.read(compressed_size)

        # Decompress and decode
        decompressed = zstd.decompress(compressed_data)
        return bson.decode(decompressed)


def parse_block_section(section_data):
    """Parse block section to get palette and blocks array"""
    reader = io.BytesIO(section_data)

    # Read header
    migration_count = struct.unpack('>I', reader.read(4))[0]
    palette_type = struct.unpack('>B', reader.read(1))[0]
    palette_size = struct.unpack('>H', reader.read(2))[0]

    # Read palette
    palette = {}
    for i in range(palette_size):
        if palette_type == 3:  # Short
            internal_id = struct.unpack('>H', reader.read(2))[0]
        else:
            internal_id = struct.unpack('>B', reader.read(1))[0]

        name_length = struct.unpack('>H', reader.read(2))[0]
        block_name = reader.read(name_length).decode('utf-8')
        count = struct.unpack('>H', reader.read(2))[0]
        palette[internal_id] = block_name

    # Read blocks array
    if palette_type == 0:  # Empty
        return palette, None, palette_type
    elif palette_type == 1:
        blocks_array = reader.read(16384)
    elif palette_type == 2:
        blocks_array = reader.read(32768)
    elif palette_type == 3:
        blocks_array = reader.read(65536)
    else:
        return palette, None, palette_type

    return palette, blocks_array, palette_type


def get_block_at(palette, blocks_array, palette_type, x, y, z):
    """Get block at local coordinates (0-31)"""
    if blocks_array is None:
        return "Empty"

    # Calculate flat index (Y-Z-X ordering)
    flat_idx = ((y & 31) << 10) | ((z & 31) << 5) | (x & 31)

    # Get internal ID
    if palette_type == 1:  # HalfByte
        byte_idx = flat_idx // 2
        if flat_idx % 2 == 0:
            internal_id = blocks_array[byte_idx] & 0x0F
        else:
            internal_id = (blocks_array[byte_idx] >> 4) & 0x0F
    elif palette_type == 2:  # Byte
        internal_id = blocks_array[flat_idx]
    elif palette_type == 3:  # Short
        internal_id = struct.unpack('>H', blocks_array[flat_idx*2:flat_idx*2+2])[0]
    else:
        return "Empty"

    return palette.get(internal_id, "Empty")


def find_surface_height(chunk_data, x, z):
    """
    Find the top solid block at column (x, z)
    Returns: (height, block_name, section_index)
    """
    sections = chunk_data["Components"]["ChunkColumn"]["Sections"]

    # Scan from top to bottom
    for section_idx in range(9, -1, -1):  # Y sections 9 down to 0
        section = sections[section_idx]

        if "Block" not in section["Components"]:
            continue

        block_data = section["Components"]["Block"]["Data"]
        palette, blocks_array, palette_type = parse_block_section(block_data)

        if blocks_array is None:
            continue

        # Check blocks in this section from top (Y=31) to bottom (Y=0)
        for local_y in range(31, -1, -1):
            block_name = get_block_at(palette, blocks_array, palette_type, x, local_y, z)

            # Skip air blocks
            if block_name == "Empty" or block_name.startswith("*"):
                continue

            # Found solid block
            world_y = section_idx * 32 + local_y
            return world_y, block_name, section_idx

    return 0, "Empty", 0


def get_block_color(block_name):
    """
    Simple color mapping for common blocks
    In a full implementation, this would load from Assets
    """
    # Basic color palette
    colors = {
        "Empty": (0, 0, 0),
        "Soil_Grass": (103, 182, 45),
        "Soil_Dirt": (139, 90, 43),
        "Rock_Stone": (128, 128, 128),
        "Rock_Stone_Cobble": (100, 100, 100),
        "Wood_Beech_Trunk": (139, 90, 43),
        "Plant_Grass_Lush": (50, 200, 50),
        "Plant_Leaves": (34, 139, 34),
        "Sand": (238, 214, 175),
        "Water": (63, 118, 228),
    }

    # Check exact match
    if block_name in colors:
        return colors[block_name]

    # Check partial matches
    for key in colors:
        if key in block_name or block_name.startswith(key):
            return colors[key]

    # Check common prefixes
    if "Grass" in block_name or "Plant" in block_name:
        return (80, 180, 60)
    elif "Stone" in block_name or "Rock" in block_name:
        return (120, 120, 120)
    elif "Wood" in block_name or "Trunk" in block_name:
        return (139, 90, 43)
    elif "Soil" in block_name or "Dirt" in block_name:
        return (139, 90, 43)
    elif "Water" in block_name:
        return (63, 118, 228)
    elif "Leaves" in block_name:
        return (34, 139, 34)

    # Default gray
    return (128, 128, 128)


def calculate_shading(height, neighbors):
    """
    Calculate terrain shading based on slope
    neighbors: (N, S, W, E, NW, NE, SW, SE)
    Returns: shading multiplier (0.0 - 1.0+)
    """
    n, s, w, e, nw, ne, sw, se = neighbors

    # Calculate gradients
    dhdx = (e - w) / 2.0
    dhdz = (s - n) / 2.0

    # Vertical scale factor
    dy = 3.0

    # Surface normal
    nx = dhdx
    ny = dy
    nz = dhdz

    # Normalize
    length = math.sqrt(nx*nx + ny*ny + nz*nz)
    if length > 0:
        nx /= length
        ny /= length
        nz /= length

    # Light direction (from top-left-front)
    lx, ly, lz = -0.2, 0.8, 0.5
    length = math.sqrt(lx*lx + ly*ly + lz*lz)
    lx /= length
    ly /= length
    lz /= length

    # Diffuse lighting
    lambert = max(0.0, nx * lx + ny * ly + nz * lz)

    # 40% ambient + 60% diffuse
    return 0.4 + 0.6 * lambert


def render_chunk(chunk_x, chunk_z, output_path="chunk.png"):
    """
    Render a chunk to a 32x32 PNG image

    Args:
        chunk_x: Chunk X coordinate (world_x // 32)
        chunk_z: Chunk Z coordinate (world_z // 32)
        output_path: Output PNG file path
    """
    print(f"Rendering chunk ({chunk_x}, {chunk_z})...")

    # Read chunk data
    chunk_data = read_chunk_data(chunk_x, chunk_z)
    if chunk_data is None:
        return

    # Create 32x32 heightmap
    print("Building heightmap...")
    heights = [[0 for _ in range(32)] for _ in range(32)]
    blocks = [["Empty" for _ in range(32)] for _ in range(32)]

    for z in range(32):
        for x in range(32):
            height, block_name, _ = find_surface_height(chunk_data, x, z)
            heights[z][x] = height
            blocks[z][x] = block_name

    # Create image
    print("Rendering image...")
    img = Image.new('RGB', (32, 32))
    pixels = img.load()

    for z in range(32):
        for x in range(32):
            height = heights[z][x]
            block_name = blocks[z][x]

            # Get base color
            r, g, b = get_block_color(block_name)

            # Get neighbor heights for shading
            n = heights[z-1][x] if z > 0 else height
            s = heights[z+1][x] if z < 31 else height
            w = heights[z][x-1] if x > 0 else height
            e = heights[z][x+1] if x < 31 else height
            nw = heights[z-1][x-1] if z > 0 and x > 0 else height
            ne = heights[z-1][x+1] if z > 0 and x < 31 else height
            sw = heights[z+1][x-1] if z < 31 and x > 0 else height
            se = heights[z+1][x+1] if z < 31 and x < 31 else height

            # Calculate shading
            shade = calculate_shading(height, (n, s, w, e, nw, ne, sw, se))

            # Apply shading
            r = int(min(255, r * shade))
            g = int(min(255, g * shade))
            b = int(min(255, b * shade))

            # Set pixel
            pixels[x, z] = (r, g, b)

    # Save image
    img.save(output_path)
    print(f"Saved to {output_path}")
    print(f"Image size: {img.width}x{img.height}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python render_chunk.py <chunk_x> <chunk_z> [output.png]")
        print()
        print("Example: python render_chunk.py 0 2")
        print("  Renders chunk at world coordinates (0-31, ?, 64-95)")
        sys.exit(1)

    chunk_x = int(sys.argv[1])
    chunk_z = int(sys.argv[2])
    output = sys.argv[3] if len(sys.argv) > 3 else f"chunk_{chunk_x}_{chunk_z}.png"

    render_chunk(chunk_x, chunk_z, output)
