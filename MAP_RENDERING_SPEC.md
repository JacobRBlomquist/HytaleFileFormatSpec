# Hytale World Map Rendering Specification

**Version:** 1.0
**Date:** 2026-01-22
**Source:** Decompiled from `ImageBuilder.java`, `GeneratorChunkWorldMap.java`, and `Biome.java`

---

## Table of Contents

1. [Overview](#overview)
2. [Rendering Pipeline](#rendering-pipeline)
3. [Color Calculation Algorithm](#color-calculation-algorithm)
4. [Asset Data Structures](#asset-data-structures)
5. [Chunk Data Requirements](#chunk-data-requirements)
6. [Implementation Details](#implementation-details)
7. [Examples](#examples)

---

## Overview

The Hytale world map rendering system generates overhead map images from chunk data by:
1. Sampling surface block colors from the heightmap
2. Blending biome-specific tints with block colors
3. Applying dynamic lighting based on terrain slope
4. Overlaying fluid colors (water/lava) with depth-based transparency

The renderer produces visually appealing maps that accurately represent terrain features, biomes, and water bodies.

### Key Features

- **Biome-based tinting**: Blocks change color based on biome
- **Terrain shading**: Height differences create realistic shadows/highlights
- **Fluid rendering**: Water and lava with depth-based transparency
- **Efficient sampling**: Configurable resolution from chunk data

---

## Rendering Pipeline

The complete rendering pipeline for each pixel:

```
┌─────────────────────────────────────────────────────────────┐
│ Input: Chunk Data                                           │
│  • Height at (x,z)                                          │
│  • Biome tint color                                         │
│  • Block ID at surface                                      │
│  • Neighbor heights (8 directions)                          │
│  • Optional: Fluid ID, depth, environment ID                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Get Block Base Color                                │
│  • Load block asset data                                    │
│  • Apply biome tinting                                      │
│  • Blend with particle color                                │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Apply Terrain Shading                               │
│  • Calculate surface normal from height gradients           │
│  • Compute Lambert diffuse lighting                         │
│  • Apply ambient + diffuse shading                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Blend Fluid Color (if present)                      │
│  • Apply environment water tint                             │
│  • Multiply by fluid particle color                         │
│  • Blend with terrain based on depth                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Output: Final RGBA color                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Color Calculation Algorithm

### Step 1: Block Color with Biome Tinting

**Source:** `ImageBuilder.getBlockColor()` (lines 410-442)

#### Algorithm

```python
def get_block_color(block_id, biome_tint_color, assets):
    # Extract biome tint RGB components
    biome_tint_r = (biome_tint_color >> 16) & 0xFF
    biome_tint_g = (biome_tint_color >> 8) & 0xFF
    biome_tint_b = (biome_tint_color >> 0) & 0xFF

    # Get block's own tint color (default white if not specified)
    block = assets.get_block(block_id)
    if block.tint_up and len(block.tint_up) > 0:
        self_tint_r = block.tint_up[0].red
        self_tint_g = block.tint_up[0].green
        self_tint_b = block.tint_up[0].blue
    else:
        self_tint_r = 255
        self_tint_g = 255
        self_tint_b = 255

    # Get biome tint multiplier (0-100%)
    biome_tint_multiplier = block.biome_tint_up / 100.0

    # Blend biome tint with block tint
    tint_color_r = self_tint_r + (biome_tint_r - self_tint_r) * biome_tint_multiplier
    tint_color_g = self_tint_g + (biome_tint_g - self_tint_g) * biome_tint_multiplier
    tint_color_b = self_tint_b + (biome_tint_b - self_tint_b) * biome_tint_multiplier

    # Apply particle color if present and biome tint < 100%
    if block.particle_color and biome_tint_multiplier < 1.0:
        tint_color_r = (tint_color_r * block.particle_color.red) / 255
        tint_color_g = (tint_color_g * block.particle_color.green) / 255
        tint_color_b = (tint_color_b * block.particle_color.blue) / 255

    return Color(tint_color_r, tint_color_g, tint_color_b, 255)
```

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `block_id` | int | Block type ID from chunk data |
| `biome_tint_color` | int | RGB packed as 24-bit integer (R<<16 \| G<<8 \| B) |
| `assets` | AssetLoader | Asset manager for loading block data |

#### Block Asset Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `TintUp` | string[] | Block's base tint colors (hex) | `["#67b62d"]` |
| `BiomeTintUp` | int | Biome influence percentage (0-100) | `100` |
| `ParticleColor` | string | Particle/override color (hex) | `"#eae8e8"` |

#### Examples

**Example 1: Grass Block (100% biome tinted)**
```
Block: Soil_Grass
  TintUp: ["#67b62d"]  (green)
  BiomeTintUp: 100
  ParticleColor: "#eae8e8"  (light gray)

Biome: Plains
  Biome tint: #68c030  (bright green)

Calculation:
  biome_multiplier = 100 / 100.0 = 1.0
  final_color = #67b62d + (#68c030 - #67b62d) * 1.0
              = #68c030  (fully biome-tinted)
```

**Example 2: Stone Block (0% biome tinted)**
```
Block: Rock_Stone
  TintUp: ["#808080"]  (gray)
  BiomeTintUp: 0
  ParticleColor: "#808080"

Biome: Any
  Biome tint: #68c030

Calculation:
  biome_multiplier = 0 / 100.0 = 0.0
  final_color = #808080 + (#68c030 - #808080) * 0.0
              = #808080  (no biome influence)
```

---

### Step 2: Terrain Shading

**Source:** `ImageBuilder.shadeFromHeights()` (lines 372-408)

#### Algorithm

Terrain shading uses height gradients to compute a surface normal, then applies Lambert diffuse lighting.

```python
def shade_from_heights(
    block_pixel_x, block_pixel_z,  # Subpixel position
    block_pixel_width, block_pixel_height,  # Block size in pixels
    height,  # Center height
    north, south, west, east,  # Cardinal neighbors
    north_west, north_east, south_west, south_east  # Diagonal neighbors
):
    # Normalized position within block (0-1)
    u = (block_pixel_x + 0.5) / block_pixel_width
    v = (block_pixel_z + 0.5) / block_pixel_height

    # Diagonal coordinates
    ud = (u + v) / 2.0
    vd = (1.0 - u + v) / 2.0

    # Height gradients (bilinear interpolation)
    dhdx1 = (height - west) * (1.0 - u) + (east - height) * u
    dhdz1 = (height - north) * (1.0 - v) + (south - height) * v

    dhdx2 = (height - north_west) * (1.0 - ud) + (south_east - height) * ud
    dhdz2 = (height - north_east) * (1.0 - vd) + (south_west - height) * vd

    # Weighted average of gradients
    dhdx = dhdx1 * 2.0 + dhdx2
    dhdz = dhdz1 * 2.0 + dhdz2

    # Surface normal (dy = vertical scale)
    dy = 3.0
    nx = dhdx
    ny = dy
    nz = dhdz

    # Normalize normal vector
    inv_s = 1.0 / sqrt(nx*nx + ny*ny + nz*nz)
    nx *= inv_s
    ny *= inv_s
    nz *= inv_s

    # Light direction (from top-left-front)
    lx = -0.2
    ly = 0.8
    lz = 0.5

    # Normalize light direction
    inv_l = 1.0 / sqrt(lx*lx + ly*ly + lz*lz)
    lx *= inv_l
    ly *= inv_l
    lz *= inv_l

    # Lambert diffuse: dot(normal, light)
    lambert = max(0.0, nx*lx + ny*ly + nz*lz)

    # Final shading: 40% ambient + 60% diffuse
    ambient = 0.4
    diffuse = 0.6
    return ambient + diffuse * lambert
```

#### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `dy` | 3.0 | Vertical scale factor for normal calculation |
| `light_direction` | (-0.2, 0.8, 0.5) | Normalized light vector (top-left-front) |
| `ambient` | 0.4 (40%) | Minimum brightness (ambient light) |
| `diffuse` | 0.6 (60%) | Maximum additional brightness (diffuse) |

#### Shading Range

- **Minimum:** 0.4 (facing away from light)
- **Maximum:** 1.0 (facing directly toward light)
- **Typical:** 0.6-0.9 (most terrain)

#### Examples

**Example 1: Flat Terrain**
```
All neighbors at same height:
  height = 64, all neighbors = 64

Gradients:
  dhdx = 0, dhdz = 0

Normal:
  n = (0, 3.0, 0) → normalized = (0, 1, 0) (pointing up)

Lambert:
  dot((0,1,0), (-0.2,0.8,0.5)) = 0.8

Shade:
  0.4 + 0.6 * 0.8 = 0.88 (bright, facing up)
```

**Example 2: Steep North-Facing Slope**
```
Heights:
  center = 64
  north = 70 (+6)
  south = 58 (-6)
  all other neighbors = 64

Gradients:
  dhdz ≈ -6 (slope downward to south)
  dhdx ≈ 0

Normal:
  n ≈ (0, 3.0, -6) → normalized ≈ (0, 0.45, -0.89)

Lambert:
  dot((0, 0.45, -0.89), (-0.2, 0.8, 0.5)) ≈ 0.36 - 0.445 ≈ -0.085 → 0 (clamped)

Shade:
  0.4 + 0.6 * 0.0 = 0.4 (dark, facing away from light)
```

---

### Step 3: Fluid Color Blending

**Source:** `ImageBuilder.getFluidColor()` (lines 444-470)

#### Algorithm

```python
def get_fluid_color(fluid_id, environment_id, fluid_depth, terrain_color, assets):
    # Start with white
    tint_r = 255
    tint_g = 255
    tint_b = 255

    # Apply environment water tint
    environment = assets.get_environment(environment_id)
    if environment.water_tint:
        tint_r = (tint_r * environment.water_tint.red) / 255
        tint_g = (tint_g * environment.water_tint.green) / 255
        tint_b = (tint_b * environment.water_tint.blue) / 255

    # Apply fluid particle color
    fluid = assets.get_fluid(fluid_id)
    if fluid.particle_color:
        tint_r = (tint_r * fluid.particle_color.red) / 255
        tint_g = (tint_g * fluid.particle_color.green) / 255
        tint_b = (tint_b * fluid.particle_color.blue) / 255

    # Blend with terrain based on depth
    depth_multiplier = min(1.0, 1.0 / fluid_depth)

    final_r = tint_r + (terrain_color.r - tint_r) * depth_multiplier
    final_g = tint_g + (terrain_color.g - tint_g) * depth_multiplier
    final_b = tint_b + (terrain_color.b - tint_b) * depth_multiplier

    return Color(final_r, final_g, final_b, 255)
```

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `fluid_id` | int | Fluid type ID (water, lava, etc.) |
| `environment_id` | int | Environment ID for water tinting |
| `fluid_depth` | int | Depth of fluid in blocks (1-320) |
| `terrain_color` | Color | Base terrain color to blend with |

#### Asset Fields

**Environment:**
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `WaterTint` | string | Hex color for water | `"#66682b"` (swamp green) |

**Fluid:**
| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `ParticleColor` | string | Hex color for fluid | `"#3f76e4"` (water blue) |

#### Depth Blending

The depth multiplier controls transparency:

```
depth_multiplier = min(1.0, 1.0 / fluid_depth)
```

| Depth | Multiplier | Effect |
|-------|------------|---------|
| 1 block | 1.0 | 100% terrain visible (shallow) |
| 2 blocks | 0.5 | 50% terrain, 50% water |
| 3 blocks | 0.33 | 33% terrain, 67% water |
| 5+ blocks | ≤0.2 | ≥80% water (opaque) |

#### Examples

**Example 1: Shallow Water (1 block deep)**
```
Terrain color: RGB(100, 150, 50)  (grass)
Fluid: Water
  Particle color: #3f76e4  (63, 118, 228)
Environment: Default (no tint)

Calculation:
  tint_color = (255, 255, 255) * (63, 118, 228) / 255
             = (63, 118, 228)

  depth_multiplier = 1.0 / 1 = 1.0

  final = (63, 118, 228) + ((100, 150, 50) - (63, 118, 228)) * 1.0
        = (100, 150, 50)  (terrain fully visible)
```

**Example 2: Deep Water (5 blocks deep)**
```
Terrain color: RGB(100, 150, 50)
Fluid: Water (same as above)

Calculation:
  tint_color = (63, 118, 228)
  depth_multiplier = 1.0 / 5 = 0.2

  final = (63, 118, 228) + ((100, 150, 50) - (63, 118, 228)) * 0.2
        = (63, 118, 228) + (37, 32, -178) * 0.2
        = (63, 118, 228) + (7, 6, -36)
        = (70, 124, 192)  (mostly water color)
```

**Example 3: Swamp Water with Tint**
```
Environment: Swamp
  WaterTint: #66682b  (102, 104, 43)  (murky green)

Calculation:
  tint_color = (255, 255, 255) * (102, 104, 43) / 255
             = (102, 104, 43)

  tint_color = (102, 104, 43) * (63, 118, 228) / 255
             = (25, 48, 38)  (dark greenish water)
```

---

## Asset Data Structures

### Block Type Asset

**Location:** `Assets/Server/Item/Items/*/*.json`

```json
{
  "BlockType": {
    "TintUp": ["#67b62d"],
    "BiomeTintUp": 100,
    "ParticleColor": "#eae8e8",
    "TextureSideMask": "...",
    "..."
  }
}
```

**Required Fields:**
- `TintUp`: Array of hex color strings for block tint
- `BiomeTintUp`: Integer 0-100, percentage of biome influence
- `ParticleColor`: Hex color string for particle/override color

### Biome Asset

**Location:** `Assets/Server/World/*/Zones/*/*.json`

```json
{
  "MapColor": "#993333",
  "Weight": 15,
  "Covers": [...],
  "..."
}
```

**Required Fields:**
- `MapColor`: Hex color string representing biome base color

### Environment Asset

**Location:** `Assets/Server/Environments/*/*.json`

```json
{
  "WaterTint": "#66682b",
  "SpawnDensity": 0.9,
  "WeatherForecasts": {...}
}
```

**Required Fields:**
- `WaterTint`: Hex color string for water tinting (optional)

### Fluid Asset

**Location:** Asset map (referenced by fluid ID)

```json
{
  "ParticleColor": "#3f76e4"
}
```

**Required Fields:**
- `ParticleColor`: Hex color string for fluid color

---

## Chunk Data Requirements

### Input Data Per Position

For each (x, z) position in a chunk (0-31):

| Data | Type | Source | Description |
|------|------|--------|-------------|
| `height` | int16 | `worldChunk.getHeight(x, z)` | Surface block Y coordinate |
| `biome_tint` | int32 | `worldChunk.getTint(x, z)` | Biome tint RGB (R<<16\|G<<8\|B) |
| `block_id` | int32 | `worldChunk.getBlock(x, height, z)` | Block type ID at surface |

### Optional Fluid Data

| Data | Type | Source | Description |
|------|------|--------|-------------|
| `fluid_id` | int32 | `fluidSection.getFluidId(x, y, z)` | Fluid type (0 = none) |
| `fluid_depth` | int16 | Calculated | Blocks of fluid above surface |
| `environment_id` | int32 | `blockChunk.getEnvironment(x, y, z)` | Environment ID for tinting |

### Neighbor Heights

For shading, 8 neighbor heights are required:

```
     NW    N    NE
       \   |   /
    W - Center - E
       /   |   \
     SW    S    SE
```

These can be:
- From the same chunk (for interior pixels)
- From adjacent chunks (for edge pixels)
- Edge-replicated or set to center height if unavailable

---

## Implementation Details

### Memory-Mapped Index Access

The `worldChunk` data is accessed via memory-mapped byte buffers for performance:

**Height:** `worldChunk.getHeight(x, z) → short`
- Returns Y coordinate of highest solid block

**Tint:** `worldChunk.getTint(x, z) → int`
- Returns RGB packed as 24-bit integer
- Format: `(R << 16) | (G << 8) | B`

**Block ID:** `worldChunk.getBlock(x, y, z) → int`
- Returns block type identifier

### Chunk Resolution

**Default:** 32×32 blocks per chunk

**Image Resolution:** Configurable
- Typically 32×32 pixels (1:1 mapping)
- Can be scaled up/down (e.g., 64×64, 16×16)
- Scaling affects which blocks are sampled

### Sampling Strategy

```python
sample_width = min(32, image_width)
sample_height = min(32, image_height)
block_step_x = max(1, 32 // image_width)
block_step_z = max(1, 32 // image_height)

for image_pixel in range(image_width * image_height):
    # Map pixel to sample coordinate
    sample_x = int(pixel_x * (sample_width / image_width))
    sample_z = int(pixel_z * (sample_height / image_height))

    # Map sample to block coordinate
    block_x = sample_x * block_step_x
    block_z = sample_z * block_step_z

    # Sample data at block position
    height = chunk.getHeight(block_x, block_z)
    ...
```

### Color Packing

**Hytale Format (RGBA):**
```
packed = (R << 24) | (G << 16) | (B << 8) | A
```

**Standard RGB (for PNG/JPG):**
```
packed = (R << 16) | (G << 8) | B
```

### Performance Optimizations

1. **Asset Caching:** Load and cache block/biome/environment assets
2. **Parallel Rendering:** Render multiple chunks concurrently
3. **Neighbor Pre-padding:** Pad height arrays to avoid bounds checks
4. **Vectorization:** Use SIMD operations for color blending (NumPy)

---

## Examples

### Example 1: Flat Plains Chunk

**Input Data:**
```python
heights = np.full((32, 32), 64)  # All at Y=64
biome_tints = np.full((32, 32), 0x68c030)  # Plains green
block_ids = np.ones((32, 32))  # All grass
```

**Expected Output:**
- Uniform green color (from grass + plains biome)
- Brightness ~0.88 (flat terrain facing up)
- Final color: ~RGB(93, 170, 42)

### Example 2: Mountain Ridge

**Input Data:**
```python
# Create ridge along X axis
for x in range(32):
    for z in range(32):
        heights[z, x] = 64 + abs(16 - z) * 2  # Ridge at z=16

biome_tints = np.full((32, 32), 0x808080)  # Gray (mountain)
block_ids = np.full((32, 32), 2)  # Stone blocks
```

**Expected Output:**
- North-facing slope: darker (~0.4 shade)
- South-facing slope: brighter (~0.9 shade)
- Ridge top: medium brightness (~0.7 shade)

### Example 3: Lake with Depth Variation

**Input Data:**
```python
heights = np.full((32, 32), 64)
biome_tints = np.full((32, 32), 0x67b62d)
block_ids = np.ones((32, 32))  # Grass/dirt

# Add circular lake
for x in range(32):
    for z in range(32):
        dist = math.sqrt((x-16)**2 + (z-16)**2)
        if dist < 10:
            fluid_ids[z, x] = 1  # Water
            fluid_depths[z, x] = int(10 - dist)  # Deeper in center
```

**Expected Output:**
- Terrain visible around edges (shallow water)
- Deep blue center (5+ blocks deep)
- Gradual transition from terrain to water color

---

## Appendix A: Color Format Reference

### Hex Color Format

**6-digit (RGB):** `#RRGGBB`
```
Example: #67b62d
  R = 0x67 = 103
  G = 0xb6 = 182
  B = 0x2d = 45
```

**8-digit (RGBA):** `#RRGGBBAA`
```
Example: #67b62dff
  R = 0x67 = 103
  G = 0xb6 = 182
  B = 0x2d = 45
  A = 0xff = 255 (opaque)
```

### Integer Color Format

**24-bit RGB:**
```
value = (R << 16) | (G << 8) | B
Example: 0x68c030
  R = 0x68 = 104
  G = 0xc0 = 192
  B = 0x30 = 48
```

**32-bit RGBA:**
```
value = (R << 24) | (G << 16) | (B << 8) | A
```

---

## Appendix B: Coordinate Systems

### Chunk Coordinates

**Origin:** Northwest corner (0, 0)
**X-axis:** East (positive) → West (negative)
**Z-axis:** South (positive) → North (negative)
**Y-axis:** Up (positive) → Down (negative)

```
      Z=0
       ↓
X=0 →  +----+----+----+
       |0,0 |1,0 |2,0 |
       +----+----+----+
       |0,1 |1,1 |2,1 |
       +----+----+----+
       |0,2 |1,2 |2,2 |
       +----+----+----+
```

### Image Coordinates

**Origin:** Top-left (0, 0)
**i-axis (width):** Right (positive)
**j-axis (height):** Down (positive)

Maps directly to chunk X, Z coordinates.

---

## Appendix C: Implementation Checklist

### Phase 1: Basic Rendering
- [ ] Load block type assets (TintUp, BiomeTintUp, ParticleColor)
- [ ] Implement `get_block_color()` with biome tinting
- [ ] Render flat chunks with correct colors

### Phase 2: Terrain Shading
- [ ] Load neighbor heights from chunk data
- [ ] Implement `shade_from_heights()` with gradient calculation
- [ ] Apply lighting to rendered chunks

### Phase 3: Fluid Rendering
- [ ] Load fluid and environment assets
- [ ] Implement `get_fluid_color()` with depth blending
- [ ] Render water/lava overlays

### Phase 4: Optimization
- [ ] Cache loaded assets
- [ ] Parallelize chunk rendering
- [ ] Optimize neighbor height access
- [ ] Profile and optimize hot paths

### Phase 5: Full Integration
- [ ] Load all asset types from JSON files
- [ ] Map block IDs to block names
- [ ] Handle missing/invalid data gracefully
- [ ] Generate multi-chunk world maps

---

**End of Specification**
