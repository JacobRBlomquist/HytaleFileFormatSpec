#!/usr/bin/env python3
"""
Simple chunk renderer - generates a top-down map image of a single chunk
"""
import sys
import struct
import math
import io
import json
from pathlib import Path
sys.path.insert(0, "..")
import compression.zstd as zstd
import bson
from PIL import Image

# BASE_PATH = "SRV/universe/worlds/default/chunks"
BASE_PATH = "C:/Users/Jacob/AppData/Roaming/Hytale/UserData/Saves/2026-01-30/universe/worlds/default_world/chunks"
HEADER_LENGTH = 32

# Cache for block properties
_block_properties = None


def load_block_properties():
    """Load block properties from JSON file (cached)"""
    global _block_properties
    if _block_properties is None:
        properties_path = Path(__file__).parent / "block_properties.json"
        with open(properties_path, 'r') as f:
            _block_properties = json.load(f)
    return _block_properties


def hex_to_rgb(hex_color):
    """Convert hex color string to RGB tuple"""
    if not hex_color or not hex_color.startswith('#'):
        return None
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join([c*2 for c in hex_color])
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

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


def parse_biome_tints(chunk_data):
    """
    Parse heightmap and biome tint colors from BlockChunk.Data
    Returns: (heightmap, tint_colors) where heightmap is 32x32 shorts and tint_colors is 32x32 RGB tuples
    """
    if 'BlockChunk' not in chunk_data['Components']:
        return None

    block_chunk_data = chunk_data['Components']['BlockChunk']['Data']
    reader = io.BytesIO(block_chunk_data)

    # Read needsPhysics (1 byte)
    needs_physics = struct.unpack('B', reader.read(1))[0]

    # Parse ShortBytePalette (heightmap) - 10-bit indices
    height_count = struct.unpack('<H', reader.read(2))[0]

    # Read height palette (short values)
    height_palette = []
    for i in range(height_count):
        height = struct.unpack('<H', reader.read(2))[0]
        height_palette.append(height)

    # Read packed height indices
    height_packed_len = struct.unpack('<I', reader.read(4))[0]
    height_packed_data = reader.read(height_packed_len)

    # Unpack 10-bit indices (1024 values, 1280 bytes)
    heightmap = [[0 for _ in range(32)] for _ in range(32)]
    for i in range(1024):
        # Extract 10-bit value from packed data
        bit_offset = i * 10
        byte_offset = bit_offset // 8
        bit_in_byte = bit_offset % 8

        # Read 2 bytes to get the 10-bit value
        if byte_offset + 1 < len(height_packed_data):
            byte1 = height_packed_data[byte_offset]
            byte2 = height_packed_data[byte_offset + 1] if byte_offset + 1 < len(height_packed_data) else 0

            # Extract 10 bits
            value = ((byte1 >> bit_in_byte) | (byte2 << (8 - bit_in_byte))) & 0x3FF

            # Map to x, z coordinates (Z-major: index = z * 32 + x)
            x = i % 32
            z = i // 32

            # Look up height in palette
            if value < len(height_palette):
                heightmap[z][x] = height_palette[value]
            else:
                heightmap[z][x] = 0  # Fallback

    # Parse IntBytePalette (biome tints)
    tint_count = struct.unpack('<H', reader.read(2))[0]

    # Read tint palette (RGB colors)
    tint_palette = []
    for i in range(tint_count):
        rgb_int = struct.unpack('<I', reader.read(4))[0]
        r = (rgb_int >> 16) & 0xFF
        g = (rgb_int >> 8) & 0xFF
        b = rgb_int & 0xFF
        tint_palette.append((r, g, b))

    # Read packed tint indices
    tint_packed_len = struct.unpack('<I', reader.read(4))[0]
    tint_packed_data = reader.read(tint_packed_len)

    # Unpack 10-bit indices (1024 values, 1280 bytes)
    tint_colors = [[None for _ in range(32)] for _ in range(32)]
    for i in range(1024):
        # Extract 10-bit value from packed data
        bit_offset = i * 10
        byte_offset = bit_offset // 8
        bit_in_byte = bit_offset % 8

        # Read 2 bytes to get the 10-bit value
        if byte_offset + 1 < len(tint_packed_data):
            byte1 = tint_packed_data[byte_offset]
            byte2 = tint_packed_data[byte_offset + 1] if byte_offset + 1 < len(tint_packed_data) else 0

            # Extract 10 bits
            value = ((byte1 >> bit_in_byte) | (byte2 << (8 - bit_in_byte))) & 0x3FF

            # Map to x, z coordinates (data stored in column-major order: Z varies fastest)
            z = i % 32
            x = i // 32

            # Look up color in palette
            if value < len(tint_palette):
                tint_colors[z][x] = tint_palette[value]
            else:
                tint_colors[z][x] = (255, 255, 255)  # White fallback

    return heightmap, tint_colors


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


def parse_fluid_section(fluid_data):
    """Parse fluid section to get type palette, type array, and level array"""
    reader = io.BytesIO(fluid_data)

    # Check if we have enough data for header
    if len(fluid_data) < 3:
        return {}, None, None, 0

    # Read header (no migration_count for fluids)
    palette_type_bytes = reader.read(1)
    if len(palette_type_bytes) < 1:
        return {}, None, None, 0
    palette_type = struct.unpack('>B', palette_type_bytes)[0]

    palette_size_bytes = reader.read(2)
    if len(palette_size_bytes) < 2:
        return {}, None, None, 0
    palette_size = struct.unpack('>H', palette_size_bytes)[0]

    # Read type palette
    type_palette = {}
    for i in range(palette_size):
        try:
            if palette_type == 3:  # Short
                internal_id = struct.unpack('>H', reader.read(2))[0]
            else:
                internal_id = struct.unpack('>B', reader.read(1))[0]

            name_length = struct.unpack('>H', reader.read(2))[0]
            fluid_name = reader.read(name_length).decode('utf-8')
            count = struct.unpack('>H', reader.read(2))[0]
            type_palette[internal_id] = fluid_name
        except:
            # Malformed palette entry, return empty
            return type_palette, None, None, palette_type

    # Read type data array based on palette type
    if palette_type == 0:  # Empty
        return type_palette, None, None, palette_type
    elif palette_type == 1:  # HalfByte
        type_array = reader.read(16384)
    elif palette_type == 2:  # Byte
        type_array = reader.read(32768)
    elif palette_type == 3:  # Short
        type_array = reader.read(65536)
    else:
        return type_palette, None, None, palette_type

    # Verify we got the expected array size
    if len(type_array) == 0:
        return type_palette, None, None, palette_type

    # Read level data array (ALWAYS 4-bit, 16384 bytes)
    level_array = reader.read(16384)

    # Verify we got the expected level array size
    if len(level_array) < 16384:
        return type_palette, None, None, palette_type

    return type_palette, type_array, level_array, palette_type


def get_fluid_at(type_palette, type_array, level_array, palette_type, x, y, z):
    """Get fluid type and level at local coordinates (0-31)"""
    if type_array is None or level_array is None:
        return None, 0

    # Calculate flat index (Y-Z-X ordering)
    flat_idx = ((y & 31) << 10) | ((z & 31) << 5) | (x & 31)

    # Get fluid type internal ID
    if palette_type == 1:  # HalfByte
        byte_idx = flat_idx // 2
        if flat_idx % 2 == 0:
            type_id = type_array[byte_idx] & 0x0F
        else:
            type_id = (type_array[byte_idx] >> 4) & 0x0F
    elif palette_type == 2:  # Byte
        type_id = type_array[flat_idx]
    elif palette_type == 3:  # Short
        type_id = struct.unpack('>H', type_array[flat_idx*2:flat_idx*2+2])[0]
    else:
        return None, 0

    fluid_type = type_palette.get(type_id)
    if not fluid_type or fluid_type == "Empty":
        return None, 0

    # Get fluid level (always 4-bit)
    byte_idx = flat_idx // 2
    if flat_idx % 2 == 0:
        level = level_array[byte_idx] & 0x0F
    else:
        level = (level_array[byte_idx] >> 4) & 0x0F

    return fluid_type, level


def blend_fluid_color(terrain_color, fluid_type, fluid_level):
    """Blend fluid color over terrain based on depth

    Uses hardcoded colors:
    - Water: #1983d9 (Zone1 default)
    - Lava: #f94e11 (from Fluid_Lava.json ParticleColor)
    """
    if not fluid_type or fluid_level == 0:
        return terrain_color

    # Get base fluid color (hardcoded)
    if "Water" in fluid_type:
        # Zone1 WaterTint: #1983d9 = RGB(25, 131, 217)
        fluid_color = (25, 131, 217)
    elif "Lava" in fluid_type:
        # Lava ParticleColor: #f94e11 = RGB(249, 78, 17)
        fluid_color = (249, 78, 17)
    else:
        # Unknown fluid, return terrain
        return terrain_color

    # Blend based on depth (level 0-15, higher = deeper)
    # Algorithm from ImageBuilder.getFluidColor:
    # depth_multiplier = min(1.0, 1.0 / fluid_level)
    # final = fluid_color + (terrain_color - fluid_color) * depth_multiplier
    depth_multiplier = min(1.0, 1.0 / max(1, fluid_level))

    r = int(fluid_color[0] + (terrain_color[0] - fluid_color[0]) * depth_multiplier)
    g = int(fluid_color[1] + (terrain_color[1] - fluid_color[1]) * depth_multiplier)
    b = int(fluid_color[2] + (terrain_color[2] - fluid_color[2]) * depth_multiplier)

    # Clamp to valid range
    r = min(255, max(0, r))
    g = min(255, max(0, g))
    b = min(255, max(0, b))

    return (r, g, b)


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


def find_surface_fluid(chunk_data, x, z, surface_y):
    """
    Find the topmost fluid and calculate its depth from surface
    Depth = (top of water column Y) - (surface block Y)
    Returns: (fluid_type, fluid_depth)
    """
    sections = chunk_data["Components"]["ChunkColumn"]["Sections"]

    fluid_type = None
    topmost_fluid_y = None

    # Scan from top down to just above surface to find fluid column
    for world_y in range(319, surface_y, -1):
        section_idx = world_y // 32

        if section_idx >= len(sections):
            continue

        section = sections[section_idx]
        if "Fluid" not in section["Components"]:
            continue

        fluid_data = section["Components"]["Fluid"].get("Data")
        if not fluid_data or len(fluid_data) < 3:
            continue

        type_palette, type_array, level_array, palette_type = parse_fluid_section(fluid_data)

        if type_array is None or level_array is None:
            continue

        local_y = world_y % 32
        current_fluid, fluid_level = get_fluid_at(type_palette, type_array, level_array, palette_type, x, local_y, z)

        if current_fluid and fluid_level > 0:
            if fluid_type is None:
                # Found the topmost fluid
                fluid_type = current_fluid
                topmost_fluid_y = world_y
            elif current_fluid != fluid_type:
                # Different fluid type, stop
                break
        elif fluid_type is not None:
            # Was in fluid, hit air/empty, stop
            break

    if fluid_type and topmost_fluid_y is not None:
        # Depth is distance from surface to top of water
        fluid_depth = topmost_fluid_y - surface_y
        return fluid_type, fluid_depth

    return None, 0


def get_block_color(block_name, biome_tint=None):
    """
    Get block color from block_properties.json with optional biome tinting

    Args:
        block_name: Name of the block
        biome_tint: Optional (r, g, b) tuple for biome tinting

    Returns:
        (r, g, b) color tuple
    """
    if block_name == "Empty":
        return (0, 0, 0)

    # Load properties
    properties = load_block_properties()

    base_color = None
    biome_tint_percent = 0
    particle_color = None

    # Check exact match
    if block_name in properties:
        block_props = properties[block_name]

        # Get TintUp as base color if available
        if block_props.get("TintUp"):
            base_color = hex_to_rgb(block_props["TintUp"][0])
            biome_tint_percent = block_props.get("BiomeTintUp", 0)

        # Get ParticleColor if available
        if block_props.get("ParticleColor"):
            pc = hex_to_rgb(block_props["ParticleColor"])
            if pc:
                particle_color = pc

        # If no TintUp, use ParticleColor as base
        if not base_color and particle_color:
            base_color = particle_color
            particle_color = None  # Don't multiply twice

    # Try partial matches (for blocks with state suffixes)
    if not base_color:
        for key in properties:
            if block_name.startswith(key):
                block_props = properties[key]

                # Get TintUp as base color
                if block_props.get("TintUp"):
                    base_color = hex_to_rgb(block_props["TintUp"][0])
                    biome_tint_percent = block_props.get("BiomeTintUp", 0)

                # Get ParticleColor
                if block_props.get("ParticleColor"):
                    pc = hex_to_rgb(block_props["ParticleColor"])
                    if pc:
                        particle_color = pc

                # If no TintUp, use ParticleColor as base
                if not base_color and particle_color:
                    base_color = particle_color
                    particle_color = None

                if base_color:
                    break

    # Fallback colors
    if not base_color:
        print(f"Warning: Using fallback color for block '{block_name}'")

        if "Grass" in block_name:
            base_color = (103, 182, 45)
        elif "Leaves" in block_name:
            base_color = (75, 133, 25)
        elif "Stone" in block_name or "Rock" in block_name:
            base_color = (120, 120, 120)
        elif "Wood" in block_name or "Trunk" in block_name:
            base_color = (120, 90, 50)
        elif "Dirt" in block_name or "Soil" in block_name:
            base_color = (139, 90, 43)
        elif "Sand" in block_name:
            base_color = (220, 215, 200)
        elif "Water" in block_name:
            base_color = (63, 118, 228)
        else:
            print(f"Warning: Using default gray for unknown block '{block_name}'")
            base_color = (128, 128, 128)

    # Apply biome tinting if available
    if biome_tint and biome_tint_percent > 0:
        multiplier = biome_tint_percent / 100.0
        r = int(base_color[0] * (1.0 - multiplier) + biome_tint[0] * multiplier)
        g = int(base_color[1] * (1.0 - multiplier) + biome_tint[1] * multiplier)
        b = int(base_color[2] * (1.0 - multiplier) + biome_tint[2] * multiplier)
        base_color = (r, g, b)

        # Apply ParticleColor ONLY if biome tint < 100%
        # (as per map_renderer.py line 168: "if particle_color_str and biome_tint_multiplier < 1.0")
        if particle_color and multiplier < 1.0:
            r = (base_color[0] * particle_color[0]) // 255
            g = (base_color[1] * particle_color[1]) // 255
            b = (base_color[2] * particle_color[2]) // 255
            base_color = (r, g, b)
    elif particle_color:
        # No biome tinting, just apply ParticleColor
        r = (base_color[0] * particle_color[0]) // 255
        g = (base_color[1] * particle_color[1]) // 255
        b = (base_color[2] * particle_color[2]) // 255
        base_color = (r, g, b)

    return base_color


def calculate_shading(height, neighbors, pixel_x=0.5, pixel_z=0.5):
    """
    Calculate terrain shading based on slope using heightmap gradients.
    Based on ImageBuilder.shadeFromHeights()

    Args:
        height: Center height
        neighbors: (N, S, W, E, NW, NE, SW, SE)
        pixel_x: Sub-pixel X position within block (0.0-1.0)
        pixel_z: Sub-pixel Z position within block (0.0-1.0)

    Returns: shading multiplier (0.0 - 1.0+)
    """
    n, s, w, e, nw, ne, sw, se = neighbors

    # Normalized position within block
    u = pixel_x
    v = pixel_z

    # Diagonal coordinates for diagonal gradient sampling
    ud = (u + v) / 2.0
    vd = (1.0 - u + v) / 2.0

    # Calculate height gradients in X and Z directions
    # Using bilinear interpolation of neighbors
    dhdx1 = (height - w) * (1.0 - u) + (e - height) * u
    dhdz1 = (height - n) * (1.0 - v) + (s - height) * v

    dhdx2 = (height - nw) * (1.0 - ud) + (se - height) * ud
    dhdz2 = (height - ne) * (1.0 - vd) + (sw - height) * vd

    # Weighted average of gradients (2:1 ratio)
    dhdx = dhdx1 * 2.0 + dhdx2
    dhdz = dhdz1 * 2.0 + dhdz2

    # Vertical scale factor
    dy = 3.0

    # Compute surface normal from gradients
    nx = dhdx
    ny = dy
    nz = dhdz

    # Normalize the normal vector
    inv_s = 1.0 / math.sqrt(nx * nx + ny * ny + nz * nz)
    nx *= inv_s
    ny *= inv_s
    nz *= inv_s

    # Light direction (from top-left-front)
    lx = -0.2
    ly = 0.8
    lz = 0.5

    # Normalize light direction
    inv_l = 1.0 / math.sqrt(lx * lx + ly * ly + lz * lz)
    lx *= inv_l
    ly *= inv_l
    lz *= inv_l

    # Lambert diffuse lighting (dot product)
    lambert = max(0.0, nx * lx + ny * ly + nz * lz)

    # Final shading: 40% ambient + 60% diffuse
    ambient = 0.4
    diffuse = 0.6
    return ambient + diffuse * lambert


def render_chunk(chunk_x, chunk_z, output_path="chunk.png", pixels_per_block=2, enable_shading=True):
    """
    Render a chunk to a PNG image

    Args:
        chunk_x: Chunk X coordinate (world_x // 32)
        chunk_z: Chunk Z coordinate (world_z // 32)
        output_path: Output PNG file path
        pixels_per_block: Resolution multiplier (1=32x32, 2=64x64, etc.)
        enable_shading: Whether to apply terrain shading (default True)
    """
    print(f"Rendering chunk ({chunk_x}, {chunk_z})...")

    # Read chunk data
    chunk_data = read_chunk_data(chunk_x, chunk_z)
    if chunk_data is None:
        return

    # Parse heightmap and biome tints
    print("Parsing heightmap and biome tints...")
    parsed_data = parse_biome_tints(chunk_data)
    if parsed_data is None:
        print("Warning: No chunk data found")
        return

    heights, biome_tints = parsed_data

    # Get block names at each surface position
    print("Reading surface blocks...")
    blocks = [["Empty" for _ in range(32)] for _ in range(32)]
    for z in range(32):
        for x in range(32):
            height = heights[z][x]
            # Get block at this height
            _, block_name, _ = find_surface_height(chunk_data, x, z)
            blocks[z][x] = block_name

    # Create image
    print(f"Rendering image at {pixels_per_block}x resolution...")
    img_size = 32 * pixels_per_block
    img = Image.new('RGB', (img_size, img_size))
    pixels = img.load()

    for z in range(32):
        for x in range(32):
            height = heights[z][x]
            block_name = blocks[z][x]

            # Get biome tint for this position
            biome_tint = biome_tints[z][x] if biome_tints else None

            # Get base color with biome tinting
            base_r, base_g, base_b = get_block_color(block_name, biome_tint)

            # Get neighbor heights for shading
            n = heights[z-1][x] if z > 0 else height
            s = heights[z+1][x] if z < 31 else height
            w = heights[z][x-1] if x > 0 else height
            e = heights[z][x+1] if x < 31 else height
            nw = heights[z-1][x-1] if z > 0 and x > 0 else height
            ne = heights[z-1][x+1] if z > 0 and x < 31 else height
            sw = heights[z+1][x-1] if z < 31 and x > 0 else height
            se = heights[z+1][x+1] if z < 31 and x < 31 else height

            # Check for fluid once per block
            fluid_type, fluid_depth = find_surface_fluid(chunk_data, x, z, height)

            # Render each pixel within this block
            for sub_z in range(pixels_per_block):
                for sub_x in range(pixels_per_block):
                    # Calculate sub-pixel position (0.0 to 1.0)
                    pixel_x = (sub_x + 0.5) / pixels_per_block
                    pixel_z = (sub_z + 0.5) / pixels_per_block

                    # Calculate shading with sub-pixel position
                    if enable_shading:
                        shade = calculate_shading(height, (n, s, w, e, nw, ne, sw, se), pixel_x, pixel_z)
                    else:
                        shade = 1.0

                    # Apply shading
                    r = int(min(255, base_r * shade))
                    g = int(min(255, base_g * shade))
                    b = int(min(255, base_b * shade))

                    # Apply fluid if present
                    if fluid_type and fluid_depth > 0:
                        r, g, b = blend_fluid_color((r, g, b), fluid_type, fluid_depth)

                    # Set pixel in image
                    pixel_img_x = x * pixels_per_block + sub_x
                    pixel_img_z = z * pixels_per_block + sub_z
                    pixels[pixel_img_x, pixel_img_z] = (r, g, b)

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
