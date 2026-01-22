import base64
import struct
import logging
import compression.zstd as zstd
import io
import bson

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

HEADER_LEN = 32
REGION_WIDTH_CHUNKS = 32


def read_header(file):
    logger.debug("===READING HEADER===")
    header = file.read(HEADER_LEN)
    magic, version, blob_count, segment_size = struct.unpack(">20sIII", header)
    logger.debug("Magic: %s", magic.decode("utf-8"))
    logger.debug("Version: %d", version)
    logger.debug("Blob Count: %d", blob_count)
    logger.debug("Segment Size: %d", segment_size)

    return (magic.decode("utf-8"), version, blob_count, segment_size)

def decode_blocks(blocks):
    '''
    Decode blocks array (WIP)

    | offset   | size | Field Name                   |  Type  | Description                                                                                               | Default? |
    |----------|------|------------------------------|--------|-----------------------------------------------------------------------------------------------------------|----------|
    | 0x0      | 4    | Unknown                      | int32  | Unknown                                                                                                   | 0xA      |
    | 0x4      | 1    | Packing?                     | int8   | something to do with how blocks are packed into bytes. 0x01 => 4 bits per block 0x02 => 8 bites per block | NA       |
    | 0x5      | 2    | palette Length               | int16  | Number of entries in palette                                                                              | NA       |
    | 0x7      | 1    | Unknown                      | int8   | UNknown                                                                                                   | 0x00     |
    [REPEAT FOR EACH ITEM IN PALETTE]=================================================================================================================================================
    | 0x8      | 2    | Entry Name Length            | int16  | Name Length of block in palette position                                                                  | NA       |
    | 0xA      | N    | Entry Name                   | string | Name of block                                                                                             | NA       |
    | 0xA + N  | 2    | Entry quantity in section?   | int16  | might be quantity of block in section                                                                     | NA       |
    | ...      | 1    | UNKNOWN                      | int8   | unknown                                                                                                   | NA       |
    [END REPEAT]======================================================================================================================================================================
    [BEGIN PACKED BLOCK DATA]=========================================================================================================================================================
    If packing is 1, each nibble in the next 16,384 bytes (32 * 32 * 32 / 2) is an index into the
    palette above
    If packing is 2, each byte in next 32,768 is index.
    Need to find a chunk section with more than 255 unique blocks to see other examples. My
    gut feeling is that 3 would be 2 bytes per index, 4, 4 etc. 
    THEORY: bitsPerIndex = 2 ^ (packing - 1) * 4
    [END PACKED BLOCK DATA]===========================================================================================================================================================
    there is a lot of... something else at the end. Maybe lighting data? maybe just extra space to prevent realloc?
    not sure yet.
    '''
    with io.BytesIO(blocks) as b:
        unknown1, packing_factor, palette_length, unknown2 = struct.unpack(">Ibhb", b.read(8))
        logger.debug("Unknown 1: %s", hex(unknown1))
        logger.debug("Packing factor?: %s", hex(packing_factor))
        logger.debug("Palette Length: %d", palette_length)
        logger.debug("Unknown 2: %s\n", hex(unknown2))
        logger.debug("READING PALETTE")

        palette = []

        for i in range(palette_length):
            name_length = struct.unpack(">h", b.read(2))[0]
            name = b.read(name_length).decode("utf-8")
            quantity, unknown3 = struct.unpack(">hb", b.read(3))
            logger.debug("  %d -> %s", i, name)
            logger.debug("    quantity?: %d", quantity)
            logger.debug("    unknown3: %s", hex(unknown3))

            palette.append(name)

        logger.debug("Palette: \n %s", palette)



    

def read_chunk(file, x, z, segment_size):
    """
    Reads a chunk in the file (x,z)

    :param file: file handle
    :param x: chunk x coordinate relative to region
    :param z: chunk z coordinate relative to region
    :param segment_size: segment size in region file (so far always 4096)
    """
    logger.debug("===READING CHUNK %d,%d===", x, z)
    # offset into the chunk location table at beginning of file
    index_offset = (x + z * REGION_WIDTH_CHUNKS) * 4
    file.seek(HEADER_LEN + index_offset)
    # 1. Get segment number in region file
    segment = struct.unpack(">I", file.read(4))[0]
    location = segment * segment_size + HEADER_LEN
    logger.debug("(X,Z)=>(%d,%d) Segment: %d, Offset: %d", 0, 0, segment, location)

    # 2. Read Chunk Sizes (decompressed, then compressed sizes)
    file.seek(location)
    uncompressed_size, compressed_size = struct.unpack(">II", file.read(8))
    logger.debug("Uncompressed Chunk Size (bytes): %d", uncompressed_size)
    logger.debug("Compressed Chunk Size (bytes): %d", compressed_size)
    compressed_bytes = file.read(compressed_size)

    # 3. decompress chunk using zstd
    decompressed = zstd.decompress(compressed_bytes)

    # 4. Deserialize BSON
    chunk = bson.decode(decompressed)
    # at this point chunk is a dictionary containing the chunk data
    # we are interested in `Components.ChunkColumn.Sections`
    # this array contains 10 sections.
    # each section contains fluid information and Block information

    # 5. Read blocks of section
    SECTION = 0
    logger.debug("===SECTION %d===", SECTION)
    section = chunk["Components"]["ChunkColumn"]["Sections"][SECTION]
    block_version = section["Components"]["Block"]["Version"]
    blocks = section["Components"]["Block"]["Data"]

    logger.debug("Block version: %d", block_version)
    logger.debug("Section 0 block len (bytes): %d", len(blocks))

    chunk_filename = f"chunk-{x}-{z}-{SECTION}.blocks"
    logger.info("Dumping chunk to %s", chunk_filename)
    with open(chunk_filename, "wb") as f:
        f.write(blocks)
    
    decode_blocks(blocks)


def main(filePath):
    """"""
    with open(filePath, "rb") as file:
        magic, version, blob_count, segment_size = read_header(file)
        read_chunk(file, 0, 0, segment_size)


if __name__ == "__main__":
    path = "./WORLD/universe/worlds/default/chunks/-1.0.region.bin"
    main(path)
