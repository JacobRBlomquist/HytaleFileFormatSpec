#!/usr/bin/env python3
"""
Renders multiple chunks into a single map image
"""
import sys
from PIL import Image
from render_chunk import read_chunk_data, find_surface_height, find_surface_fluid
from render_chunk import get_block_color, calculate_shading, blend_fluid_color, parse_biome_tints


def render_map(start_x, start_z, end_x, end_z, output_path="map.png", pixels_per_block=2, enable_shading=True):
    """
    Render a range of chunks into a single map image

    Args:
        start_x: Starting chunk X coordinate
        start_z: Starting chunk Z coordinate
        end_x: Ending chunk X coordinate (inclusive)
        end_z: Ending chunk Z coordinate (inclusive)
        output_path: Output PNG file path
        pixels_per_block: Resolution multiplier (1=32px/chunk, 2=64px/chunk, etc.)
        enable_shading: Whether to apply terrain shading (default True)
    """
    chunks_width = end_x - start_x + 1
    chunks_height = end_z - start_z + 1

    print(f"Rendering {chunks_width}x{chunks_height} chunks ({chunks_width * chunks_height} total)")
    print(f"Chunk range: ({start_x}, {start_z}) to ({end_x}, {end_z})")
    print(f"Resolution: {pixels_per_block}x pixels per block")

    # Create output image
    img_width = chunks_width * 32 * pixels_per_block
    img_height = chunks_height * 32 * pixels_per_block
    img = Image.new('RGB', (img_width, img_height))
    pixels = img.load()

    # Render each chunk
    for chunk_z in range(start_z, end_z + 1):
        for chunk_x in range(start_x, end_x + 1):
            print(f"Rendering chunk ({chunk_x}, {chunk_z})...")

            # Read chunk data
            chunk_data = read_chunk_data(chunk_x, chunk_z)
            if chunk_data is None:
                print(f"  Chunk ({chunk_x}, {chunk_z}) not found, skipping")
                continue

            # Parse heightmap and biome tints
            parsed_data = parse_biome_tints(chunk_data)
            if parsed_data is None:
                print(f"  Chunk ({chunk_x}, {chunk_z}) has no data, skipping")
                continue

            heights, biome_tints = parsed_data

            # Get block names at each surface position
            blocks = [["Empty" for _ in range(32)] for _ in range(32)]
            for z in range(32):
                for x in range(32):
                    height = heights[z][x]
                    # Get block at this height
                    _, block_name, _ = find_surface_height(chunk_data, x, z)
                    blocks[z][x] = block_name

            # Render pixels for this chunk
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

                            # Calculate pixel position in final image
                            pixel_img_x = (chunk_x - start_x) * 32 * pixels_per_block + x * pixels_per_block + sub_x
                            pixel_img_z = (chunk_z - start_z) * 32 * pixels_per_block + z * pixels_per_block + sub_z

                            # Set pixel
                            pixels[pixel_img_x, pixel_img_z] = (r, g, b)

    # Save image
    img.save(output_path)
    print(f"Saved to {output_path}")
    print(f"Image size: {img.width}x{img.height}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python render_map.py <start_chunk_x> <start_chunk_z> <end_chunk_x> <end_chunk_z> [output.png] [pixels_per_block] [--no-shading]")
        print()
        print("Example: python render_map.py -2 -2 2 2")
        print("  Renders a 5x5 grid of chunks at 2x resolution (320x320 pixels)")
        print()
        print("Example: python render_map.py 0 0 3 3 my_map.png 2")
        print("  Renders a 4x4 grid of chunks at 2x resolution (256x256 pixels)")
        print()
        print("Example: python render_map.py 0 0 3 3 my_map.png 2 --no-shading")
        print("  Renders without terrain shading (flat colors)")
        print()
        print("  pixels_per_block: 1=32px/chunk (blocky), 2=64px/chunk (smooth, default)")
        sys.exit(1)

    start_x = int(sys.argv[1])
    start_z = int(sys.argv[2])
    end_x = int(sys.argv[3])
    end_z = int(sys.argv[4])
    output = sys.argv[5] if len(sys.argv) > 5 and not sys.argv[5].isdigit() and sys.argv[5] != '--no-shading' else f"map_{start_x}_{start_z}_to_{end_x}_{end_z}.png"
    pixels_per_block = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] != '--no-shading' else (int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].isdigit() else 2)
    enable_shading = '--no-shading' not in sys.argv

    render_map(start_x, start_z, end_x, end_z, output, pixels_per_block, enable_shading)
