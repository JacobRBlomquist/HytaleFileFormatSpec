# Hytale File Formats Specification

Complete technical documentation of Hytale's save file formats, derived from source code analysis using javap disassembly.

## Table of Contents

1. [Region File Format (IndexedStorageFile)](#region-file-format)
2. [Block Storage Format (Section Palettes)](#block-storage-format)
3. [Chunk Data Format (BlockChunk)](#chunk-data-format)
4. [Palette Compression Format](#palette-compression-format)

---

## Region File Format

Region files (`.region.bin`) use the IndexedStorageFile format for storing multiple chunks in a single file.

### File Structure

```
[32-byte Header]
[Memory-mapped Blob Index Table: 4 bytes × blobCount]
[Segment Data: variable size]
```

### Header Format (32 bytes, Big-Endian)

| Offset | Size | Type   | Field        | Description                           |
|--------|------|--------|--------------|---------------------------------------|
| 0      | 20   | String | MAGIC_STRING | Magic identifier (ASCII)              |
| 20     | 4    | int    | VERSION      | File format version (1)               |
| 24     | 4    | int    | BLOB_COUNT   | Number of chunks (default: 1024)      |
| 28     | 4    | int    | SEGMENT_SIZE | Bytes per segment (default: 4096)     |

**Constants from IndexedStorageFile.class:**
- `MAGIC_STRING` = 20 bytes
- `VERSION_OFFSET` = 20
- `BLOB_COUNT_OFFSET` = 24
- `SEGMENT_SIZE_OFFSET` = 28
- `HEADER_LENGTH` = 32

### Blob Index Table

Immediately following the header, starting at offset 32.

**Format:**
- Size: `blobCount × 4` bytes (typically 1024 × 4 = 4096 bytes)
- Entry format: 4-byte unsigned integer (memory-mapped, big-endian)
- Index calculation: `index_offset = 32 + (chunkX + chunkZ * 32) * 4`

**Index Entry Value:**
- `0` = Chunk not present
- `>0` = File segment number where chunk data starts

**Chunk Location Calculation:**
```python
file_segment = struct.unpack(">I", index_entry)[0]  # Big-endian
chunk_offset = file_segment * segment_size + HEADER_LENGTH
```

### Blob (Chunk) Format

Each blob starts at a segment boundary.

**Blob Header (8 bytes):**

| Offset | Size | Type | Field              | Description                    |
|--------|------|------|--------------------|--------------------------------|
| 0      | 4    | int  | UNCOMPRESSED_SIZE  | Size before compression        |
| 4      | 4    | int  | COMPRESSED_SIZE    | Size of compressed data        |
| 8      | var  | byte[] | COMPRESSED_DATA  | ZSTD compressed BSON document |

**Constants:**
- `BLOB_HEADER_LENGTH` = 8
- `SRC_LENGTH_OFFSET` = 0 (uncompressed size)
- `COMPRESSED_LENGTH_OFFSET` = 4

**Decompression:**
```python
import zstd
import bson

# Read blob header
uncompressed_size, compressed_size = struct.unpack(">II", file.read(8))

# Read and decompress
compressed_data = file.read(compressed_size)
decompressed = zstd.decompress(compressed_data)

# Parse BSON
chunk_data = bson.decode(decompressed)
```

### Segment Allocation

- Segments are allocated contiguously
- A blob may span multiple segments
- Required segments: `math.ceil((BLOB_HEADER_LENGTH + compressed_size) / segment_size)`
- Used segments are tracked in a `BitSet` for efficient allocation

### Migration from v0

IndexedStorageFile_v0 uses a different format. When opening a v0 file with version=0, it automatically migrates:
1. Creates new v1 file with `.migrating` suffix
2. Copies all blobs from v0 to v1
3. Moves migrated file to original path
4. Deletes v0 file

---

## Block Storage Format

Block sections (32×32×32 blocks) use palette-based compression with direct internal ID storage.

### Section Palette Types

Sections automatically promote/demote based on unique block count:

| Palette Type          | Max Unique Blocks | Storage Size   | Bytes per Block | Demote Threshold |
|-----------------------|-------------------|----------------|-----------------|------------------|
| EmptySectionPalette   | 1 (air only)      | 0 bytes        | 0               | N/A              |
| HalfByteSectionPalette| 16                | 16,384 bytes   | 4 bits          | N/A              |
| ByteSectionPalette    | 256               | 32,768 bytes   | 1 byte          | ≤14 blocks       |
| ShortSectionPalette   | 65,536            | 65,536 bytes   | 2 bytes         | N/A              |

### Block Section Serialization Format (Big-Endian)

**Header:**

| Offset | Size | Type  | Field            | Description                           |
|--------|------|-------|------------------|---------------------------------------|
| 0      | 4    | int   | MIGRATION_COUNT  | Block migration asset count           |
| 4      | 1    | byte  | PALETTE_TYPE     | 0=Empty, 1=HalfByte, 2=Byte, 3=Short  |
| 5      | 2    | short | PALETTE_SIZE     | Number of unique blocks in palette    |

**Palette Entries (repeat `PALETTE_SIZE` times):**

| Size | Type   | Field       | Description                        |
|------|--------|-------------|------------------------------------|
| 1    | byte   | INTERNAL_ID | Internal palette index (0-255)     |
| 2    | short  | NAME_LENGTH | Length of block name string        |
| var  | string | NAME        | Block identifier (UTF-8)           |
| 2    | short  | COUNT       | Number of blocks using this entry  |

**Blocks Array:**
- Follows palette entries
- Total blocks: 32 × 32 × 32 = 32,768
- Stores **direct internal IDs**, not packed indices!
- Size depends on palette type:
  - **HalfByte**: 16,384 bytes (4 bits per block, 2 blocks per byte)
  - **Byte**: 32,768 bytes (1 byte per block)
  - **Short**: 65,536 bytes (2 bytes per block, big-endian)

**3D Index Calculation (Y-Z-X ordering):**
```python
# Calculate flat index using Y-Z-X ordering (from ChunkUtil.indexBlock)
flat_index = ((localY & 31) << 10) | ((localZ & 31) << 5) | (localX & 31)
# Equivalent to: localY * 1024 + localZ * 32 + localX

# Read internal ID from blocks array based on palette type
if palette_type == 1:  # HalfByte
    byte_idx = flat_index // 2
    if flat_index % 2 == 0:
        internal_id = blocks_array[byte_idx] & 0x0F
    else:
        internal_id = (blocks_array[byte_idx] >> 4) & 0x0F
elif palette_type == 2:  # Byte
    internal_id = blocks_array[flat_index]
elif palette_type == 3:  # Short
    internal_id = struct.unpack('>H', blocks_array[flat_index*2:flat_index*2+2])[0]

# Look up block name in palette
block_name = palette[internal_id]
```

### Key Implementation Details

**Storage Method:**
The blocks array stores **direct internal IDs**, not bit-packed palette indices. This is a critical difference from typical voxel storage formats:
- No bit manipulation required for lookup
- Simple array indexing
- Direct mapping from internal ID to palette entry

**Coordinate System:**
Uses Y-Z-X ordering as defined in `ChunkUtil.indexBlock(int x, int y, int z)`:
```java
// From Java source
return ((y & 31) << 10) | ((z & 31) << 5) | (x & 31);
```

**Runtime vs Storage:**
The Java runtime code uses Y-Z-X ordering, and the save file format matches this exactly.

---

## Chunk Data Format

Chunk data is stored as BSON documents within region files.

### Chunk BSON Structure

```
Components/
  ChunkColumn/
    Sections/          # Array of 10 section objects (y=0 to y=9)
      - Components/
          Block/
            Data       # BlockChunk.Data binary blob
  BlockChunk/
    Components/
      Block/
        Data           # BlockChunk.Data binary blob (alternative location)
```

### BlockChunk Class Fields (from BlockChunk.class)

**Key Fields:**
- `x`: int - Chunk X coordinate
- `z`: int - Chunk Z coordinate
- `index`: long - Chunk index (`ChunkUtil.indexChunk(x, z)`)
- `height`: ShortBytePalette - 32×32 heightmap
- `tint`: IntBytePalette - 32×32 biome tint colors
- `chunkSections`: BlockSection[10] - Array of 10 vertical sections
- `environments`: EnvironmentChunk - Biome/environment data
- `needsPhysics`: boolean - Whether physics update is needed
- `needsSaving`: boolean - Dirty flag for save

**Chunk Dimensions:**
- Horizontal: 32×32 blocks
- Vertical: 10 sections × 32 blocks = 320 blocks (y=0 to y=319)
- Each section: 32×32×32 = 32,768 blocks

### BlockChunk.Data Binary Format (Little-Endian)

BlockChunk serializes to a binary blob: `needsPhysics + height.serialize() + tint.serialize()`

**Overall Structure:**
```
[1 byte]  - needsPhysics (boolean)
[ShortBytePalette] - Heightmap
[IntBytePalette]   - Tint colors
```

### ShortBytePalette Format (Little-Endian, 32×32 shorts)

From ShortBytePalette.serialize():

```
[2 bytes]   - count (short LE) - Number of unique height values
[count × 2] - palette entries (short LE each)
[4 bytes]   - packed_length (int LE) - Size of packed data in bytes
[packed_length] - Packed indices (BitFieldArr with 10 bits per index)
```

**Key Properties:**
- Stores 1024 height values (32×32)
- Uses 10-bit indices (supports 1024 unique heights)
- BitFieldArr with `bits=10, length=1024`
- Packed array size: `(1024 * 10) / 8 = 1280 bytes`

**Index Mapping:**
```python
column_index = x + z * 32  # 0 to 1023
height = palette[packed_indices[column_index]]
```

### IntBytePalette Format (Little-Endian, 32×32 ints)

From IntBytePalette.serialize():

```
[2 bytes]   - count (short LE) - Number of unique colors
[count × 4] - palette entries (int LE each, RGB packed)
[4 bytes]   - packed_length (int LE) - Size of packed data
[packed_length] - Packed indices (BitFieldArr with 10 bits per index)
```

**RGB Packing:**
```python
# Encoding
rgb_int = (r << 16) | (g << 8) | b

# Decoding
r = (rgb_int >> 16) & 0xFF
g = (rgb_int >> 8) & 0xFF
b = rgb_int & 0xFF
```

**Key Properties:**
- Stores 1024 biome tint colors (32×32)
- Uses 10-bit indices (supports 1024 unique colors)
- Same packing as ShortBytePalette
- Packed array size: 1280 bytes

### BlockSection Structure (from BlockSection.class)

**Key Fields:**
- `chunkSection`: ISectionPalette - Block types (32×32×32)
- `fillerSection`: ISectionPalette - Filler blocks
- `rotationSection`: ISectionPalette - Block rotations
- `localLight`: ChunkLightData - Local light data
- `globalLight`: ChunkLightData - Global light data
- `tickingBlocks`: BitSet - Blocks requiring tick updates
- `loaded`: boolean - Section loaded flag

**Section Y-Index:**
```python
section_index = block_y // 32  # 0 to 9
local_y = block_y % 32         # 0 to 31
```

---

## Palette Compression Format

Both ShortBytePalette and IntBytePalette use the same compression strategy.

### Compression Algorithm

1. **Maintain Palette**: Array of unique values
2. **Track Indices**: BitFieldArr maps positions to palette indices
3. **Dynamic Sizing**: Palette grows as new values are added

### BitFieldArr Implementation

**Constructor:**
```java
BitFieldArr(int bits, int length)
// bits: bits per index (e.g., 10)
// length: number of indices (e.g., 1024)
// array: byte[(length * bits) / 8]
```

**Constants:**
- `BITS_PER_INDEX` = 10 (for both height and tint)
- `LAST_BIT_INDEX` = 9
- `INDEX_MASK` = 0x3FF (10 bits)

### Packed Data Layout

**Example with 10-bit indices:**

```
Index 0: bits 0-9 of bytes 0-1
Index 1: bits 10-19 of bytes 1-2
Index 2: bits 20-29 of bytes 2-3
...
```

**Bit Offset Calculation:**
```python
bit_offset = index * bits_per_index
byte_offset = bit_offset // 8
bit_in_byte = bit_offset % 8
```

### Optimization

**Palette Recompaction:**
- Triggered when `count >= 1024`
- Removes unused palette entries
- Rebuilds index array
- Prevents palette overflow

**Max Values:**
- ShortBytePalette: 32,767 unique values (Short.MAX_VALUE)
- IntBytePalette: 32,767 unique values (same limit)
- Practical limit with 10 bits: 1,024 unique values

---

## Endianness Summary

| Component              | Endianness    | Notes                          |
|------------------------|---------------|--------------------------------|
| Region File Header     | Big-Endian    | All header fields              |
| Region Blob Index      | Big-Endian    | Memory-mapped integers         |
| Region Blob Header     | Big-Endian    | Sizes for ZSTD data            |
| Block Section Header   | Big-Endian    | Packing factor, palette length |
| Block Section Palette  | Big-Endian    | Block names and metadata       |
| BlockChunk.Data        | Little-Endian | **Everything** in this blob    |
| ShortBytePalette       | Little-Endian | Count, palette, packed data    |
| IntBytePalette         | Little-Endian | Count, palette, packed data    |

**Critical Note:** The BlockChunk.Data binary blob uses **little-endian** for all multi-byte values, while the region file and block sections use **big-endian**. This is a key implementation detail.

---

## Implementation Examples

### Reading a Chunk from Region File

```python
import struct
import zstd
import bson

REGION_HEADER_SIZE = 32

def read_chunk(file_path, chunk_x, chunk_z):
    with open(file_path, 'rb') as f:
        # Read header (big-endian)
        header = f.read(REGION_HEADER_SIZE)
        magic, version, blob_count, segment_size = struct.unpack(">20sIII", header)

        # Read index entry
        index_offset = (chunk_x + chunk_z * 32) * 4
        f.seek(REGION_HEADER_SIZE + index_offset)
        file_segment = struct.unpack(">I", f.read(4))[0]

        if file_segment == 0:
            return None  # Chunk not present

        # Read blob
        chunk_location = file_segment * segment_size + REGION_HEADER_SIZE
        f.seek(chunk_location)
        uncompressed_size, compressed_size = struct.unpack(">II", f.read(8))
        compressed_data = f.read(compressed_size)

        # Decompress and parse
        decompressed = zstd.decompress(compressed_data)
        chunk_data = bson.decode(decompressed)

        return chunk_data
```

### Parsing BlockChunk.Data

```python
def parse_blockchunk_data(data):
    offset = 0

    # Read needsPhysics flag
    needs_physics = data[offset] != 0
    offset += 1

    # Parse ShortBytePalette (heights)
    height_count = struct.unpack('<H', data[offset:offset+2])[0]
    offset += 2

    height_palette = []
    for i in range(height_count):
        height_palette.append(struct.unpack('<H', data[offset:offset+2])[0])
        offset += 2

    height_packed_len = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    height_packed_data = data[offset:offset+height_packed_len]
    offset += height_packed_len

    # Parse IntBytePalette (tints)
    tint_count = struct.unpack('<H', data[offset:offset+2])[0]
    offset += 2

    tint_palette = []
    for i in range(tint_count):
        rgb_int = struct.unpack('<I', data[offset:offset+4])[0]
        r = (rgb_int >> 16) & 0xFF
        g = (rgb_int >> 8) & 0xFF
        b = rgb_int & 0xFF
        tint_palette.append((r, g, b))
        offset += 4

    tint_packed_len = struct.unpack('<I', data[offset:offset+4])[0]
    offset += 4
    tint_packed_data = data[offset:offset+tint_packed_len]

    return {
        'needs_physics': needs_physics,
        'height_palette': height_palette,
        'height_packed': height_packed_data,
        'tint_palette': tint_palette,
        'tint_packed': tint_packed_data
    }
```

### Parsing Block Section

```python
def parse_block_section(section_data):
    """Parse a 32x32x32 block section"""
    import struct
    import io

    reader = io.BytesIO(section_data)

    # Read header (big-endian)
    migration_count = struct.unpack('>I', reader.read(4))[0]
    palette_type = struct.unpack('>B', reader.read(1))[0]  # 0=Empty, 1=HalfByte, 2=Byte, 3=Short
    palette_size = struct.unpack('>H', reader.read(2))[0]

    # Read palette: mapping from internal ID to block name
    palette = {}
    for i in range(palette_size):
        internal_id = struct.unpack('>B', reader.read(1))[0]
        name_length = struct.unpack('>H', reader.read(2))[0]
        block_name = reader.read(name_length).decode('utf-8')
        count = struct.unpack('>H', reader.read(2))[0]
        palette[internal_id] = block_name

    # Read blocks array based on palette type
    if palette_type == 0:  # Empty
        return palette, None
    elif palette_type == 1:  # HalfByte - 4 bits per block
        blocks_array = reader.read(16384)  # 32768 blocks * 4 bits / 8
    elif palette_type == 2:  # Byte - 8 bits per block
        blocks_array = reader.read(32768)  # 32768 blocks * 1 byte
    elif palette_type == 3:  # Short - 16 bits per block
        blocks_array = reader.read(65536)  # 32768 blocks * 2 bytes
    else:
        return palette, None

    # Convert to 3D array using Y-Z-X ordering
    blocks_3d = []
    for y in range(32):
        blocks_3d.append([])
        for z in range(32):
            blocks_3d[y].append([])
            for x in range(32):
                # Calculate flat index using Y-Z-X ordering
                flat_idx = ((y & 31) << 10) | ((z & 31) << 5) | (x & 31)

                # Get internal ID from blocks array
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

                # Look up block name in palette
                if internal_id in palette:
                    blocks_3d[y][z].append(palette[internal_id])
                else:
                    blocks_3d[y][z].append("Empty")

    return palette, blocks_3d
```

### Getting a Single Block

```python
def get_block_at(section_data, x, y, z):
    """Get a single block from a section at local coordinates (0-31)"""
    import struct
    import io

    reader = io.BytesIO(section_data)

    # Read header
    migration_count = struct.unpack('>I', reader.read(4))[0]
    palette_type = struct.unpack('>B', reader.read(1))[0]
    palette_size = struct.unpack('>H', reader.read(2))[0]

    # Read palette
    palette = {}
    for i in range(palette_size):
        internal_id = struct.unpack('>B', reader.read(1))[0]
        name_length = struct.unpack('>H', reader.read(2))[0]
        block_name = reader.read(name_length).decode('utf-8')
        count = struct.unpack('>H', reader.read(2))[0]
        palette[internal_id] = block_name

    # Read blocks array
    if palette_type == 1:
        blocks_array = reader.read(16384)
    elif palette_type == 2:
        blocks_array = reader.read(32768)
    elif palette_type == 3:
        blocks_array = reader.read(65536)
    else:
        return "Empty"

    # Calculate index using Y-Z-X ordering
    flat_idx = ((y & 31) << 10) | ((z & 31) << 5) | (x & 31)

    # Get internal ID
    if palette_type == 1:
        byte_idx = flat_idx // 2
        internal_id = (blocks_array[byte_idx] & 0x0F) if flat_idx % 2 == 0 else ((blocks_array[byte_idx] >> 4) & 0x0F)
    elif palette_type == 2:
        internal_id = blocks_array[flat_idx]
    elif palette_type == 3:
        internal_id = struct.unpack('>H', blocks_array[flat_idx*2:flat_idx*2+2])[0]

    return palette.get(internal_id, "Empty")
```

---

## Version History

- **v1**: Current version with 32-byte header and memory-mapped indices
- **v0**: Legacy version, automatically migrated to v1 on open

## Important Notes

**Block Storage Discovery (2026-01-26):**
Initial analysis incorrectly assumed the block section used bit-packed palette indices. Through testing with real save files and careful re-examination of the Java bytecode, we discovered:
- The blocks array stores **direct internal IDs**, not bit-packed indices
- No bit manipulation is required for block lookup
- The palette maps internal IDs to block names directly
- Different palette types (HalfByte/Byte/Short) change the storage size per block, not packing complexity

This is simpler than typical Minecraft-style chunk formats which use bit-packed palette indices.

## References

**Source Classes:**
- `com.hypixel.hytale.storage.IndexedStorageFile`
- `com.hypixel.hytale.storage.IndexedStorageFile_v0`
- `com.hypixel.hytale.server.core.universe.world.chunk.BlockChunk`
- `com.hypixel.hytale.server.core.universe.world.chunk.section.BlockSection`
- `com.hypixel.hytale.server.core.universe.world.chunk.palette.ShortBytePalette`
- `com.hypixel.hytale.server.core.universe.world.chunk.palette.IntBytePalette`
- `com.hypixel.hytale.server.core.universe.world.chunk.palette.BitFieldArr`
- `com.hypixel.hytale.server.core.universe.world.chunk.section.palette.ISectionPalette`
- `com.hypixel.hytale.server.core.universe.world.chunk.section.palette.ByteSectionPalette`
- `com.hypixel.hytale.server.core.universe.world.chunk.section.palette.HalfByteSectionPalette`
- `com.hypixel.hytale.server.core.universe.world.chunk.section.palette.ShortSectionPalette`
- `com.hypixel.hytale.server.core.universe.world.chunk.section.palette.AbstractByteSectionPalette`

**Documentation Method:**
All information derived from javap disassembly of compiled Java classes using:
```bash
javap -c -p -v <class-file>
```
