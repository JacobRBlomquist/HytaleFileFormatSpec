# Hytale Map Rendering Algorithm

## Overview

The Hytale map renderer creates a top-down 2D map image from 3D chunk data. It simulates the in-game map view with terrain shading.

## Algorithm Steps

### 1. Find Surface Heights (Heightmap)

For each column (x, z) in the chunk (32×32 grid):

```python
# Scan from top (Y=319) to bottom (Y=0)
for section in reversed(sections):  # Y=9 down to Y=0
    for local_y in reversed(range(32)):  # Y=31 down to Y=0
        block = get_block(x, local_y, z)
        if block != "Empty":
            surface_height = section * 32 + local_y
            surface_block = block
            break
```

**Result:** 32×32 heightmap + 32×32 block type array

---

### 2. Get Base Block Color

```python
# Simple approach (your current render_chunk.py)
color = get_block_color(block_name)  # Lookup table

# Full approach (map_renderer.py)
color = block.TintUp[0]  # From block assets
biome_tint = chunk.biome_tints[x, z]
multiplier = block.BiomeTintUp / 100.0

# Blend block color with biome tint
final_color = (
    block_color * (1 - multiplier) +
    biome_tint * multiplier
)

# Apply particle color
if block.ParticleColor:
    final_color *= particle_color
```

**Input:** Block name or ID
**Output:** RGB color (0-255, 0-255, 0-255)

---

### 3. Calculate Terrain Shading

Uses slope-based lighting to show terrain elevation changes:

```python
# Get 8 neighbor heights
neighbors = {
    'N': heights[z-1][x],
    'S': heights[z+1][x],
    'W': heights[z][x-1],
    'E': heights[z][x+1],
    'NW': heights[z-1][x-1],
    'NE': heights[z-1][x+1],
    'SW': heights[z+1][x-1],
    'SE': heights[z+1][x+1]
}

# Calculate height gradients (rate of change)
dhdx = (east - west) / 2.0  # Slope in X direction
dhdz = (south - north) / 2.0  # Slope in Z direction

# Surface normal vector (perpendicular to surface)
normal = normalize([-dhdx, 3.0, -dhdz])
# where 3.0 is the vertical scale factor

# Light direction (sun position: top-left-front)
light = normalize([-0.2, 0.8, 0.5])

# Lambert diffuse shading (dot product)
lambert = max(0, dot(normal, light))

# Final shading: 40% ambient + 60% diffuse
shade = 0.4 + 0.6 * lambert
```

**Key concepts:**
- **Gradient**: How steep the terrain is
- **Normal**: Direction the surface is facing
- **Lambert**: How much the surface faces the light
- **Result**: Multiplier from ~0.4 (dark) to ~1.0 (bright)

**Visual effect:**
- Flat terrain: shade ≈ 0.4-1.0 (medium brightness)
- Slopes facing light: shade → 1.0 (bright)
- Slopes facing away: shade → 0.4 (dark)

---

### 4. Apply Shading to Color

```python
# Multiply each color channel by shade
final_r = int(base_r * shade)
final_g = int(base_g * shade)
final_b = int(base_b * shade)

# Clamp to 0-255
final_r = min(255, max(0, final_r))
final_g = min(255, max(0, final_g))
final_b = min(255, max(0, final_b))
```

---

### 5. (Optional) Blend Fluid

If water/lava is present:

```python
# Get fluid color (blue for water, orange for lava)
fluid_color = get_fluid_color(fluid_type, environment_id)

# Blend based on depth
depth_factor = 1.0 / fluid_depth
final_color = (
    fluid_color * (1 - depth_factor) +
    terrain_color * depth_factor
)
```

**Effect:**
- Shallow water: More transparent, see terrain
- Deep water: More opaque, solid water color

---

## Example Pixel Calculation

Let's render pixel at position (16, 16):

```
1. Find surface:
   Height = 120
   Block = "Soil_Grass"

2. Get base color:
   Grass color = (103, 182, 45)

3. Get neighbors:
   N=120, S=119, E=121, W=120
   NE=121, NW=120, SE=119, SW=119

4. Calculate shading:
   dhdx = (121 - 120) / 2 = 0.5
   dhdz = (119 - 120) / 2 = -0.5

   normal = normalize([-0.5, 3.0, 0.5])
          ≈ [-0.16, 0.97, 0.16]

   light = [-0.2, 0.8, 0.5] (normalized)
         ≈ [-0.21, 0.83, 0.52]

   lambert = (-0.16)*(-0.21) + (0.97)*(0.83) + (0.16)*(0.52)
           ≈ 0.92

   shade = 0.4 + 0.6 * 0.92
         = 0.95

5. Apply shading:
   final_r = 103 * 0.95 = 98
   final_g = 182 * 0.95 = 173
   final_b = 45 * 0.95 = 43

6. Result: RGB(98, 173, 43) - slightly darker grass
```

---

## Performance Notes

**For a 32×32 chunk:**
- 1,024 columns to scan
- Each column: up to 320 blocks to check
- Up to ~327,680 block lookups per chunk

**Optimizations:**
1. Parse each section once, cache the palette
2. Start from top section, skip empty sections
3. Use numpy for vectorized operations (full renderer)
4. Cache heightmaps for neighbor lookups

---

## Current Implementation

**`render_chunk.py` features:**
- ✅ Heightmap generation
- ✅ Surface block detection
- ✅ Basic color mapping (hardcoded colors)
- ✅ Terrain shading (slope-based lighting)
- ❌ Biome tinting (requires asset loading)
- ❌ Fluid rendering
- ❌ Asset-based colors (requires Assets directory)

**To add full features:**
1. Parse biome tint data from chunk
2. Load block assets (TintUp, BiomeTintUp, ParticleColor)
3. Parse fluid sections
4. Implement fluid blending

---

## Coordinate Systems

**World Coordinates:**
- X: West (-) to East (+)
- Y: Bottom (0) to Top (319)
- Z: North (-) to South (+)

**Chunk Coordinates:**
- Chunk (x, z) contains blocks from:
  - World X: [x*32, x*32+31]
  - World Z: [z*32, z*32+31]

**Image Coordinates:**
- Image (px_x, px_z) maps to chunk (px_x, px_z)
- Top-left = (0, 0)
- Bottom-right = (31, 31)

---

## Extending the Renderer

### Add Custom Block Colors

Edit `get_block_color()` in `render_chunk.py`:

```python
def get_block_color(block_name):
    colors = {
        "Your_Custom_Block": (r, g, b),
        # ...
    }
```

### Add Biome Tinting

1. Parse chunk BlockChunk.Data to get tint palette
2. Apply tinting in rendering loop

### Add Fluid Support

1. Parse Fluid sections for each Y level
2. Find fluid at surface height
3. Call `get_fluid_color()` and blend

### Increase Resolution

Change output size from 32×32 to higher:

```python
# 4x resolution (128x128 image)
img = Image.new('RGB', (128, 128))
for px_z in range(128):
    for px_x in range(128):
        chunk_x = px_x // 4
        chunk_z = px_z // 4
        # Use sub-pixel position for shading
```

---

## References

- **Java Source:** `com.hypixel.hytale.builtin.minimap.ImageBuilder.java`
- **Python Implementation:** `srcs/map_renderer.py`
- **Block Storage:** `HYTALE_FILE_FORMATS.md`
