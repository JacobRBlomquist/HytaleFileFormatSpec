import sys
import struct
import compression.zstd as zstd
from pathlib import Path
import bson
import base64
import json
import io

# BASE_PATH = "SRV/universe/worlds/default/chunks"
BASE_PATH = "C:/Users/Jacob/AppData/Roaming/Hytale/UserData/Saves/2026-01-30/universe/worlds/default_world/chunks"
HEADER_LENGTH = 32

def get_fluid(x, y, z, quiet=False):
    ''''''
    # No coordinate offsets - read directly

    # 1 calculate region
    regionX = x // 1024
    regionZ = z // 1024
    if not quiet: print(f"REGION: {regionX},{regionZ}")

    region_file_path = f"{BASE_PATH}/{regionX}.{regionZ}.region.bin"
    p = Path(region_file_path)
    if not p.exists():
        print(f"Region {region_file_path} does not exist")
        return None

    # 2 calculate chunk
    worldChunkX = x // 32
    worldChunkZ = z // 32
    if not quiet: print(f"World Chunk: {worldChunkX},{worldChunkZ}")
    relativeChunkX = worldChunkX % 32
    relativeChunkZ = worldChunkZ % 32
    if not quiet: print(f"Relative Chunk: {relativeChunkX},{relativeChunkZ}")

    # 3 open chunk
    with p.open("rb") as region:
        header = region.read(HEADER_LENGTH)
        magic, version, blob_count, segment_size = struct.unpack(">20sIII", header)
        if not quiet: print(f"M: {magic}, V: {version}, BC: {blob_count}, SS: {segment_size}")
        index_offset = (relativeChunkX + relativeChunkZ * 32) * 4
        region.seek(HEADER_LENGTH + index_offset)
        blob_segment = struct.unpack(">I", region.read(4))[0]
        chunk_location = blob_segment * segment_size + HEADER_LENGTH
        region.seek(chunk_location)

        # 4 read chunk data
        uncompressed_size, compressed_size = struct.unpack(">II", region.read(8))
        if not quiet: print(f"UNCOMPRESSED SIZE: {uncompressed_size}, COMPRESSED_SIZE: {compressed_size}, RATIO: {compressed_size/uncompressed_size}")
        compressed_bytes = region.read(compressed_size)
        decompressed = zstd.decompress(compressed_bytes)
        chunk_data = bson.decode(decompressed)

        column = chunk_data["Components"]["ChunkColumn"]
        fluids = []
        for c in column["Sections"]:
            f = c["Components"]["Fluid"]["Data"]
            fluids.append(base64.b64encode(f).decode("utf-8"))

        print(fluids)

        with open(f"CHUNK_DATA_{x}_{z}.json", 'w') as f:
            f.write(json.dumps(fluids))

        # # 5 get y segment
        # segmentY = y // 32
        # segments = chunk_data["Components"]["ChunkColumn"]["Sections"]
        # if segmentY >= len(segments):
        #     if not quiet: print("No chunk segment for target... empty")
        #     return "Empty"

        # chosen_segment = segments[segmentY]

        # # 6 Read blocks using correct format
        # blocks_data = chosen_segment["Components"]["Block"]["Data"]
        # reader = io.BytesIO(blocks_data)

        # # Parse section header (big-endian)
        # migration_count = struct.unpack('>I', reader.read(4))[0]
        # palette_type = struct.unpack('>B', reader.read(1))[0]  # 0=Empty, 1=HalfByte, 2=Byte, 3=Short
        # palette_size = struct.unpack('>H', reader.read(2))[0]

        # if not quiet:
        #     palette_names = ["Empty", "HalfByte", "Byte", "Short"]
        #     print(f"Migration count: {migration_count}, Palette type: {palette_names[palette_type]}, Palette size: {palette_size}")

        # # Read palette: mapping from internal ID to block name
        # palette = {}
        # for i in range(palette_size):
        #     internal_id = struct.unpack('>B', reader.read(1))[0]
        #     name_length = struct.unpack('>H', reader.read(2))[0]
        #     block_name = reader.read(name_length).decode('utf-8')
        #     count = struct.unpack('>H', reader.read(2))[0]
        #     palette[internal_id] = block_name
        #     if not quiet:
        #         print(f"  Palette[{internal_id}] = {block_name} (count: {count})")

        # # Read blocks array based on palette type
        # if palette_type == 0:  # Empty
        #     return "Empty"
        # elif palette_type == 1:  # HalfByte - 4 bits per block
        #     blocks_array = reader.read(16384)  # 32768 blocks * 4 bits / 8
        # elif palette_type == 2:  # Byte - 8 bits per block
        #     blocks_array = reader.read(32768)  # 32768 blocks * 1 byte
        # elif palette_type == 3:  # Short - 16 bits per block
        #     blocks_array = reader.read(65536)  # 32768 blocks * 2 bytes
        # else:
        #     if not quiet: print(f"Unknown palette type: {palette_type}")
        #     return None

        # # Calculate local coordinates within the section
        # localX = x % 32
        # localY = y % 32
        # localZ = z % 32

        # # Calculate block index using Y-Z-X ordering (as per Java code)
        # flat_idx = ((localY & 31) << 10) | ((localZ & 31) << 5) | (localX & 31)

        # if not quiet:
        #     print(f"Local coords: X={localX}, Y={localY}, Z={localZ}, Index={flat_idx}")

        # # Get internal ID from blocks array
        # if palette_type == 1:  # HalfByte
        #     byte_idx = flat_idx // 2
        #     if flat_idx % 2 == 0:
        #         internal_id = blocks_array[byte_idx] & 0x0F
        #     else:
        #         internal_id = (blocks_array[byte_idx] >> 4) & 0x0F
        # elif palette_type == 2:  # Byte
        #     internal_id = blocks_array[flat_idx]
        # elif palette_type == 3:  # Short
        #     internal_id = struct.unpack('>H', blocks_array[flat_idx*2:flat_idx*2+2])[0]
        # else:
        #     internal_id = 0

        # # Look up block name in palette
        # if internal_id in palette:
        #     return palette[internal_id]
        # else:
        #     return "Empty"

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} x y z")
        sys.exit(1)

    x = int(sys.argv[1])
    y = int(sys.argv[2])
    z = int(sys.argv[3])
    block = get_fluid(x,y,z)
    print(block)
