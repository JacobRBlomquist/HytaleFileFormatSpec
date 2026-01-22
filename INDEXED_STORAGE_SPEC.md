# Hytale IndexedStorage File Format Specification

**Version:** 1.0
**Date:** 2026-01-21
**Author:** Hypixel Studios

---

## Table of Contents

1. [Overview](#overview)
2. [File Format Version 1](#file-format-version-1)
3. [File Format Version 0 (Legacy)](#file-format-version-0-legacy)
4. [Data Types](#data-types)
5. [Compression](#compression)
6. [Concurrency](#concurrency)
7. [Operations](#operations)
8. [Migration](#migration)
9. [Implementation Notes](#implementation-notes)
10. [Examples](#examples)

---

## Overview

The Hytale IndexedStorage file format is a custom binary storage system designed for efficient chunk data persistence in Hytale. It provides:

- **Fast random access** to individual data blobs by index
- **ZSTD compression** for reduced disk usage
- **Memory-mapped indexes** for high-performance lookups
- **Thread-safe concurrent operations** using lock-free reads where possible
- **Automatic version migration** from legacy format

### Magic String

All IndexedStorage files begin with the magic string:
```
"HytaleIndexedStorage" (20 bytes, UTF-8 encoded)
```

### Current Version

The current file format version is **1**.

---

## File Format Version 1

### File Structure

```
+---------------------------+
| File Header (32 bytes)    |
+---------------------------+
| Blob Index Table          |
| (blobCount × 4 bytes)     |
+---------------------------+
| Segment Storage Area      |
| (variable length)         |
+---------------------------+
```

### 1. File Header

**Size:** 32 bytes
**Location:** Offset 0

| Offset | Size | Field Name    | Type    | Description                              | Default |
|--------|------|---------------|---------|------------------------------------------|---------|
| 0      | 20   | Magic         | byte[]  | Magic string "HytaleIndexedStorage"      | -       |
| 20     | 4    | Version       | int32   | File format version (must be 1)          | 1       |
| 24     | 4    | Blob Count    | int32   | Number of blob slots                     | 1024    |
| 28     | 4    | Segment Size  | int32   | Size of each segment in bytes            | 4096    |

**Header Constants:**
- `MAGIC_LENGTH` = 20
- `MAGIC_OFFSET` = 0
- `VERSION_OFFSET` = 20
- `BLOB_COUNT_OFFSET` = 24
- `SEGMENT_SIZE_OFFSET` = 28
- `HEADER_LENGTH` = 32

**Constraints:**
- `Blob Count` must be > 0
- `Segment Size` must be > 0
- Version must be exactly 1 for this format

---

### 2. Blob Index Table

**Size:** `blobCount × 4` bytes
**Location:** Offset 32 (immediately after header)
**Memory Mapped:** Yes (READ_WRITE)

The blob index table contains one 4-byte integer entry for each blob slot.

#### Index Entry Values

| Value | Meaning                                           |
|-------|---------------------------------------------------|
| 0     | Blob slot is empty/unassigned                     |
| ≥ 1   | First segment index where blob data begins        |

#### Index Position Calculation

```
indexPosition = HEADER_LENGTH + (blobIndex × 4)
```

Where:
- `blobIndex` is 0-based (0 to blobCount-1)
- `HEADER_LENGTH` = 32

**Example:**
- Blob 0 index: offset 32
- Blob 1 index: offset 36
- Blob 5 index: offset 52

---

### 3. Segment Storage Area

**Location:** Offset `HEADER_LENGTH + (blobCount × 4)`
**Organization:** Fixed-size segments numbered from 1

#### Segment Numbering

- Segments are numbered starting from **1** (not 0)
- Segment index 0 is reserved as the "unassigned" marker
- Segments are allocated contiguously for each blob

#### Segment Position Calculation

```
segmentsBase = HEADER_LENGTH + (blobCount × 4)
segmentOffset = (segmentIndex - 1) × segmentSize
segmentPosition = segmentsBase + segmentOffset
```

**Example with default values (segmentSize=4096, blobCount=1024):**
- Segments base: 32 + 4096 = 4128
- Segment 1 position: 4128 + 0 = 4128
- Segment 2 position: 4128 + 4096 = 8224
- Segment 3 position: 4128 + 8192 = 12320

---

### 4. Blob Data Structure

Each blob's data is stored in one or more contiguous segments, beginning with a blob header.

#### Blob Header

**Size:** 8 bytes
**Location:** First 8 bytes of the first segment

| Offset | Size | Field Name         | Type  | Description                        |
|--------|------|--------------------|-------|------------------------------------|
| 0      | 4    | Src Length         | int32 | Original uncompressed data size    |
| 4      | 4    | Compressed Length  | int32 | Compressed data size               |

**Header Constants:**
- `SRC_LENGTH_OFFSET` = 0
- `COMPRESSED_LENGTH_OFFSET` = 4
- `BLOB_HEADER_LENGTH` = 8

#### Compressed Data

**Location:** Immediately after blob header
**Size:** `Compressed Length` bytes
**Compression:** ZSTD

The compressed data begins at offset 8 of the first segment and spans as many contiguous segments as needed.

#### Segment Allocation

Number of segments required for a blob:

```
requiredSegments = ⌈(BLOB_HEADER_LENGTH + compressedLength) / segmentSize⌉
```

Example (segmentSize=4096):
- Blob with 1000 bytes compressed: ⌈(8 + 1000) / 4096⌉ = 1 segment
- Blob with 10000 bytes compressed: ⌈(8 + 10000) / 4096⌉ = 3 segments

---

### 5. Blob Storage Layout Example

**Scenario:** Blob at index 42 with 10,000 bytes compressed data

**Step 1:** Index table entry
```
Offset 200 (32 + 42×4): value = 5 (first segment index)
```

**Step 2:** Segment allocation
```
Required segments: ⌈(8 + 10000) / 4096⌉ = 3 segments
Segments used: 5, 6, 7
```

**Step 3:** Data layout in segments

**Segment 5:**
```
Offset 0-3:   Src Length (e.g., 50000)
Offset 4-7:   Compressed Length (10000)
Offset 8-4095: Compressed data (4088 bytes)
```

**Segment 6:**
```
Offset 0-4095: Compressed data continuation (4096 bytes)
```

**Segment 7:**
```
Offset 0-1815: Compressed data continuation (1816 bytes)
Offset 1816+:  Unused
```

Total data stored: 8 + 10000 = 10008 bytes across 3 segments

---

## File Format Version 0 (Legacy)

**Status:** Deprecated - automatically migrated to Version 1

### File Structure

```
+---------------------------+
| File Header (32 bytes)    |
+---------------------------+
| Blob Index Table          |
| (blobCount × 4 bytes)     |
+---------------------------+
| Temp Index Table          |
| (blobCount × 4 bytes)     |
+---------------------------+
| Segment Storage Area      |
| (variable length)         |
+---------------------------+
```

### Key Differences from Version 1

#### 1. Version Field
- Version = 0

#### 2. Dual Index Tables

**Primary Index Table:**
- Offset: 32
- Size: blobCount × 4 bytes
- Contains current blob → segment mappings

**Temporary Index Table:**
- Offset: 32 + (blobCount × 4)
- Size: blobCount × 4 bytes
- Used for atomic write operations and rollback
- Stores old segment index during writes for cleanup

#### 3. Segment Structure

Each segment in v0 has a header with a next-segment pointer, forming a linked list.

**Segment Header:**

| Offset | Size | Field Name         | Type  | Description                        |
|--------|------|--------------------|-------|------------------------------------|
| 0      | 4    | Next Segment Index | int32 | Index of next segment in chain     |

**Segment Header Constants:**
- `NEXT_SEGMENT_OFFSET` = 0
- `SEGMENT_HEADER_LENGTH` = 4

**Special Next Segment Values:**
- `0` = Segment is free/unallocated
- `Integer.MIN_VALUE` (-2147483648) = End of blob marker
- `> 0` = Index of next segment

#### 4. Blob Data Structure (v0)

**First Segment Layout:**
```
Offset 0-3:    Next Segment Index (or END_BLOB_INDEX)
Offset 4-7:    Src Length
Offset 8-11:   Compressed Length
Offset 12-N:   Compressed data
```

**Subsequent Segment Layout:**
```
Offset 0-3:    Next Segment Index (or END_BLOB_INDEX)
Offset 4-N:    Compressed data continuation
```

#### 5. Non-Contiguous Allocation

Unlike v1, v0 allows segments to be non-contiguous. Segments are chained together via the Next Segment Index field, forming a linked list.

**Example:**
- Blob starts at segment 5
- Segment 5 → Next: 12
- Segment 12 → Next: 8
- Segment 8 → Next: Integer.MIN_VALUE (end)

#### 6. Segments Base Calculation

```
segmentsBase = HEADER_LENGTH + (blobCount × 4 × 2)
```

Note: Doubled because of two index tables (primary + temporary)

#### 7. Blob Header Position (v0)

```
blobHeaderPosition = segmentPosition + SEGMENT_HEADER_LENGTH
```

---

## Data Types

All multi-byte values are stored in **big-endian** byte order (Java standard).

| Type   | Size  | Range                                      |
|--------|-------|--------------------------------------------|
| int32  | 4     | -2,147,483,648 to 2,147,483,647            |
| byte[] | N     | Raw byte array                             |

---

## Compression

### Algorithm

**ZSTD (Zstandard)** - Fast compression with good ratios

### Library

`com.github.luben:zstd-jni`

### Compression Level

- **Default:** 3
- **Range:** 1-22 (configurable)
- **Trade-off:** Higher = better compression, slower speed

### Compression Bound

Before compression, allocate buffer size:
```
maxCompressedLength = Zstd.compressBound(srcLength)
```

### Compression Process

1. Allocate direct ByteBuffer of size `BLOB_HEADER_LENGTH + maxCompressedLength`
2. Write `srcLength` at offset 0 (4 bytes)
3. Position buffer to offset 8 (after header)
4. Compress source data into buffer
5. Write actual `compressedLength` at offset 4
6. Limit buffer to actual size used
7. Write to segments

### Decompression Process

1. Read blob header to get `srcLength` and `compressedLength`
2. Read `compressedLength` bytes of compressed data
3. Decompress into buffer of `srcLength` bytes
4. Return decompressed data

### Direct ByteBuffer Requirement

ZSTD JNI library requires **direct ByteBuffers** for compression/decompression. Non-direct buffers are automatically copied to temporary direct buffers.

---

## Concurrency

### Locking Strategy

The implementation uses **StampedLock** for optimistic lock-free reads with write safety.

### Lock Types

#### 1. Index Locks (per-blob)

- **Array:** `StampedLock[blobCount]`
- **Purpose:** Protect blob index entry and associated data
- **Granularity:** One lock per blob slot

**Read Operations:**
- Acquire read lock on blob's index lock
- Read index entry
- Read blob data
- Release lock

**Write Operations:**
- Acquire write lock on blob's index lock
- Find free segments
- Write blob data
- Update index entry
- Release lock

#### 2. Segment Locks (per-segment)

- **Array:** `StampedLock[]` (dynamically sized)
- **Purpose:** Protect individual segments during allocation
- **Granularity:** One lock per segment

**Segment Range Locking:**
When allocating N contiguous segments, acquire write locks on all N segments atomically.

#### 3. Used Segments Lock

- **Type:** Single `StampedLock`
- **Purpose:** Protect the `BitSet` tracking used segments
- **Usage:** Optimistic reads, write lock for modifications

#### 4. Segment Locks Lock

- **Type:** Single `StampedLock`
- **Purpose:** Protect resizing of segment locks array
- **Usage:** Write lock when expanding array

### Optimistic Reading

Many read operations use optimistic locking:

```java
long stamp = lock.tryOptimisticRead();
// Read data
if (lock.validate(stamp)) {
    // Use data - no other thread modified it
} else {
    // Retry with actual read lock
    stamp = lock.readLock();
    try {
        // Re-read data
    } finally {
        lock.unlockRead(stamp);
    }
}
```

### Thread Safety Guarantees

- **Read operations** are lock-free in common case (optimistic reads)
- **Write operations** are fully synchronized per blob
- **Multiple readers** can access different blobs concurrently
- **Multiple writers** can write different blobs concurrently
- **Same blob** cannot be read and written simultaneously

---

## Operations

### 1. Open File

**Method:** `IndexedStorageFile.open(Path, int, int, Set<OpenOption>, FileAttribute<?>[])`

**Parameters:**
- `path` - File path
- `blobCount` - Number of blob slots (default: 1024)
- `segmentSize` - Segment size in bytes (default: 4096)
- `options` - File open options
- `attrs` - File attributes

**Process:**

1. Open FileChannel with specified options
2. **If CREATE_NEW:**
   - Create new file with header
   - Initialize empty blob index table
   - Return
3. **If CREATE and file is empty:**
   - Same as CREATE_NEW
4. **If file exists:**
   - Read and validate header
   - Memory-map blob index table
   - **If version = 0:** Migrate to version 1
   - **If version = 1:** Read used segments BitSet
   - Return

**Validation:**
- Magic string must match "HytaleIndexedStorage"
- Version must be 0 or 1
- Blob count must be > 0
- Segment size must be > 0

### 2. Read Blob

**Method:** `readBlob(int blobIndex) → ByteBuffer`

**Process:**

1. Validate `blobIndex` (0 ≤ blobIndex < blobCount)
2. Calculate index position: `indexPos = blobIndex × 4`
3. Acquire read lock on `indexLocks[blobIndex]`
4. Read `firstSegmentIndex` from mapped index at `indexPos`
5. **If firstSegmentIndex = 0:** Return null (empty blob)
6. Read blob header from `firstSegmentIndex`:
   - Position: `segmentPosition(firstSegmentIndex)`
   - Read 8 bytes: srcLength, compressedLength
7. Read compressed data:
   - Position: `segmentPosition(firstSegmentIndex) + 8`
   - Read `compressedLength` bytes
8. Release read lock
9. Decompress data with ZSTD to `srcLength` bytes
10. Return decompressed ByteBuffer

**Time Complexity:** O(1) for index lookup, O(N) for data read where N = compressed size

### 3. Write Blob

**Method:** `writeBlob(int blobIndex, ByteBuffer src)`

**Process:**

1. Validate `blobIndex` (0 ≤ blobIndex < blobCount)
2. Compress source data with ZSTD:
   - Get `srcLength` = src.remaining()
   - Allocate buffer for header + compressed data
   - Write `srcLength` to blob header
   - Compress data
   - Write `compressedLength` to blob header
3. Calculate required segments:
   - `segmentsNeeded = ⌈(8 + compressedLength) / segmentSize⌉`
4. Acquire write lock on `indexLocks[blobIndex]`
5. Read old `firstSegmentIndex` from index (for cleanup)
6. Find free contiguous segment range:
   - Search used segments BitSet for free range
   - Acquire write locks on all segments in range
7. Write blob data to segments:
   - Write full data starting at `segmentPosition(firstSegmentIndex)`
8. Force write to disk (if `flushOnWrite` enabled)
9. Update blob index with new `firstSegmentIndex`
10. Force index write to disk (if `flushOnWrite` enabled)
11. **If old blob existed:**
    - Mark old segments as free in used segments BitSet
12. Release segment range locks
13. Release index write lock

**Time Complexity:** O(M + N) where M = compression time, N = write time

### 4. Remove Blob

**Method:** `removeBlob(int blobIndex)`

**Process:**

1. Validate `blobIndex` (0 ≤ blobIndex < blobCount)
2. Calculate index position: `indexPos = blobIndex × 4`
3. Acquire write lock on `indexLocks[blobIndex]`
4. Read old `firstSegmentIndex` from index
5. **If firstSegmentIndex ≠ 0:**
   - Read blob header to get compressed length
   - Calculate old segment count
   - Write 0 to blob index (mark as empty)
   - Force index write (if `flushOnWrite` enabled)
   - Mark old segments as free in used segments BitSet
6. Release write lock

**Time Complexity:** O(1)

### 5. List Keys

**Method:** `keys() → IntList`

**Process:**

1. Create result list
2. For each blob index 0 to blobCount-1:
   - Optimistically read index entry
   - If entry ≠ 0, add blob index to result
3. Return result list

**Time Complexity:** O(blobCount)

### 6. Force/Flush

**Method:** `force(boolean metaData)`

**Process:**

1. Force FileChannel: `fileChannel.force(metaData)`
2. Force mapped blob indexes: `mappedBlobIndexes.force()`

**Purpose:** Ensure all writes are persisted to disk

### 7. Close File

**Method:** `close()`

**Process:**

1. Close FileChannel
2. Clean up memory-mapped buffer using Unsafe.invokeCleaner
3. Set mappedBlobIndexes to null

---

## Migration

### Version 0 to Version 1

**Trigger:** Opening a file with version = 0

**Process:**

1. Close v0 file
2. Rename original file to `{filename}.old`
3. Create new v1 file at original path
4. Initialize v1 file with same blobCount and segmentSize
5. Open v0 file from temporary path
6. For each blob index (0 to blobCount-1):
   - Read blob from v0 file
   - If blob exists, write to v1 file
7. Close v0 file
8. Delete temporary `.old` file
9. Return v1 file

**Changes During Migration:**

- Blob data is recompressed with same settings
- Non-contiguous segments become contiguous
- Linked segment structure removed
- Temporary index table removed
- Used segments tracked via BitSet instead of linked list

**Data Integrity:**

- Original file preserved as `.old` until migration completes
- If migration fails, `.old` file remains
- Atomic rename ensures no data loss

**Performance:**

- One-time cost on first open
- Reads and rewrites all blob data
- Time proportional to total data size

---

## Implementation Notes

### Memory Mapping

**Blob Index Table** is memory-mapped for performance:
- Mode: `READ_WRITE`
- Size: `blobCount × 4` bytes
- Position: Starts at offset `HEADER_LENGTH`

**Benefits:**
- O(1) index lookups
- OS-managed caching
- Reduced system calls

**Cleanup:**
- Uses `sun.misc.Unsafe.invokeCleaner()` for deterministic unmap
- Fallback: Set reference to null, wait for GC

### Segment Allocation Strategy

**Free Segment Search:**

1. Lock used segments BitSet for reading
2. Search BitSet for contiguous free range:
   - Use `BitSet.nextSetBit()` to skip used segments
   - Use `BitSet.nextClearBit()` to find free ranges
   - Find first range of required size
3. Attempt to acquire write locks on all segments in range
4. If any lock fails, retry from next position
5. Once all locks acquired, verify segments still free
6. Mark segments as used in BitSet
7. Return locked segment range

**Algorithm Complexity:** O(S) where S = total segments

### Buffer Management

**Thread-Local Cache:**
- Header reads use cached thread-local direct ByteBuffer
- Initial size: `HEADER_LENGTH` (32 bytes)
- Reused across operations to reduce allocation

**Direct ByteBuffers:**
- All compression/decompression uses direct buffers
- Allocated per operation for blob data
- Cleaned up with Unsafe when possible

### Error Handling

**Corrupt Data:**
- Invalid magic string → IOException
- Invalid version → IOException
- Unexpected EOF during read → IllegalStateException

**Concurrent Modification:**
- StampedLock handles coordination
- Write locks ensure consistency
- Optimistic reads retry on conflict

### Flush Modes

**Default (flushOnWrite = false):**
- Writes buffered by OS
- Faster, less durable

**Flush Enabled (flushOnWrite = true):**
- Force after each blob write
- Force after each index update
- Slower, more durable
- Recommended for critical data

### File Locking

**Method:** `lock() → FileLock`

Acquires exclusive JVM-level file lock. Use to prevent multiple processes from accessing the same file.

---

## Examples

### Example 1: Creating a New Storage File

```java
Path path = Paths.get("chunks.dat");
IndexedStorageFile storage = IndexedStorageFile.open(
    path,
    1024,  // 1024 blob slots
    4096,  // 4KB segments
    StandardOpenOption.CREATE,
    StandardOpenOption.READ,
    StandardOpenOption.WRITE
);

storage.setCompressionLevel(3);
storage.setFlushOnWrite(false);
```

**Resulting File:**

```
Offset 0-31:    Header (magic, version=1, blobCount=1024, segmentSize=4096)
Offset 32-4127: Blob index table (1024 × 4 = 4096 bytes, all zeros)
Offset 4128+:   Segment storage (initially empty)
Total size:     4128 bytes
```

### Example 2: Writing a Blob

```java
// Prepare data
ByteBuffer data = ByteBuffer.wrap("Hello, Hytale!".getBytes(StandardCharsets.UTF_8));

// Write to blob slot 42
storage.writeBlob(42, data);
```

**File Changes:**

Assuming compression reduces 14 bytes to 10 bytes:

1. **Index update** (offset 200 = 32 + 42×4):
   ```
   Before: 00 00 00 00
   After:  00 00 00 01  (points to segment 1)
   ```

2. **Segment 1 data** (offset 4128):
   ```
   Bytes 0-3:   00 00 00 0E  (srcLength = 14)
   Bytes 4-7:   00 00 00 0A  (compressedLength = 10)
   Bytes 8-17:  [compressed data]
   ```

Total file size: 4128 + 4096 = 8224 bytes (1 segment allocated)

### Example 3: Reading a Blob

```java
ByteBuffer blob = storage.readBlob(42);
if (blob != null) {
    byte[] bytes = new byte[blob.remaining()];
    blob.get(bytes);
    String text = new String(bytes, StandardCharsets.UTF_8);
    System.out.println(text);  // Output: Hello, Hytale!
}
```

**File Access:**

1. Read index at offset 200: value = 1
2. Read blob header at offset 4128: srcLength=14, compressedLength=10
3. Read compressed data at offset 4136: 10 bytes
4. Decompress to 14 bytes
5. Return decompressed buffer

### Example 4: Large Blob Spanning Multiple Segments

```java
byte[] largeData = new byte[20000];
Arrays.fill(largeData, (byte) 'A');
storage.writeBlob(100, ByteBuffer.wrap(largeData));
```

**Segment Allocation:**

Compressed size (worst case): ~20000 bytes

Required segments:
```
⌈(8 + 20000) / 4096⌉ = ⌈20008 / 4096⌉ = 5 segments
```

**File Changes:**

1. **Index update** (offset 432 = 32 + 100×4):
   ```
   Value: 00 00 00 02  (segment 2, assuming segment 1 was used)
   ```

2. **Segments 2-6 data:**
   - Segment 2: blob header + 4088 bytes data
   - Segment 3: 4096 bytes data
   - Segment 4: 4096 bytes data
   - Segment 5: 4096 bytes data
   - Segment 6: 3632 bytes data + unused space

Total size increase: 5 segments × 4096 = 20480 bytes

### Example 5: Listing All Used Blobs

```java
IntList keys = storage.keys();
System.out.println("Used blob count: " + keys.size());
for (int blobIndex : keys) {
    int length = storage.readBlobLength(blobIndex);
    int compressed = storage.readBlobCompressedLength(blobIndex);
    double ratio = (double) compressed / length * 100;
    System.out.printf("Blob %d: %d bytes → %d bytes (%.1f%%)%n",
        blobIndex, length, compressed, ratio);
}
```

**Output Example:**
```
Used blob count: 2
Blob 42: 14 bytes → 10 bytes (71.4%)
Blob 100: 20000 bytes → 18543 bytes (92.7%)
```

### Example 6: Removing a Blob

```java
storage.removeBlob(42);
```

**File Changes:**

1. **Index update** (offset 200):
   ```
   Before: 00 00 00 01
   After:  00 00 00 00
   ```

2. **Segment 1:**
   - Marked as free in used segments BitSet
   - Data remains on disk but is orphaned
   - Will be overwritten by next write

3. **File size:**
   - No change (segments not reclaimed)
   - File fragmentation increases

**Note:** The format does not shrink files or defragment. Deleted blobs leave orphaned segments that are reused for new writes.

### Example 7: Migrating from Version 0

```java
// Open a v0 file
Path v0Path = Paths.get("old_chunks.dat");
// This automatically triggers migration
IndexedStorageFile storage = IndexedStorageFile.open(
    v0Path,
    StandardOpenOption.READ,
    StandardOpenOption.WRITE
);

// File is now v1 format, v0 data has been migrated
// Original v0 file was deleted after successful migration
```

**Migration Process:**

1. Original file detected as version 0
2. Renamed to `old_chunks.dat.old`
3. New v1 file created at `old_chunks.dat`
4. All blobs copied from v0 to v1
5. Temporary `.old` file deleted
6. Returns v1 storage file

---

## Appendix A: Constants Reference

### Version 1 Constants

```java
// Magic
MAGIC_STRING = "HytaleIndexedStorage"
MAGIC_LENGTH = 20

// Version
VERSION = 1

// Defaults
DEFAULT_BLOB_COUNT = 1024
DEFAULT_SEGMENT_SIZE = 4096
DEFAULT_COMPRESSION_LEVEL = 3

// Header Offsets
MAGIC_OFFSET = 0
VERSION_OFFSET = 20
BLOB_COUNT_OFFSET = 24
SEGMENT_SIZE_OFFSET = 28
HEADER_LENGTH = 32

// Blob Header Offsets
SRC_LENGTH_OFFSET = 0
COMPRESSED_LENGTH_OFFSET = 4
BLOB_HEADER_LENGTH = 8

// Index Values
INDEX_SIZE = 4
UNASSIGNED_INDEX = 0
FIRST_SEGMENT_INDEX = 1
```

### Version 0 Constants

```java
// Version
VERSION = 0

// Segment Header
NEXT_SEGMENT_OFFSET = 0
SEGMENT_HEADER_LENGTH = 4

// Special Values
END_BLOB_INDEX = Integer.MIN_VALUE  // -2147483648
```

---

## Appendix B: File Size Calculations

### Minimum File Size (Empty)

```
minSize = HEADER_LENGTH + (blobCount × 4)
```

Example (blobCount=1024):
```
minSize = 32 + (1024 × 4) = 4128 bytes
```

### File Size with N Segments

```
fileSize = HEADER_LENGTH + (blobCount × 4) + (N × segmentSize)
```

Example (blobCount=1024, segmentSize=4096, N=100 segments):
```
fileSize = 32 + 4096 + (100 × 4096) = 413,728 bytes
```

### Maximum Theoretical Size

Limited by:
- Segment index: int32 (max ~2 billion segments)
- File size: Java FileChannel supports up to 2^63 bytes

With segmentSize=4096:
```
maxSegments = 2,147,483,647
maxDataSize ≈ 8,796,093,018,112 bytes (8 TB)
```

---

## Appendix C: Performance Characteristics

### Time Complexity

| Operation          | Average Case | Worst Case | Notes                              |
|--------------------|--------------|------------|------------------------------------|
| Open               | O(B)         | O(B + S)   | B=blobs, S=segments (v1 init)     |
| Read blob by index | O(1 + C)     | O(1 + C)   | C=compressed size                  |
| Write blob         | O(C + F)     | O(C + F)   | C=compress, F=find free segments   |
| Remove blob        | O(1)         | O(1)       | Just updates index                 |
| List keys          | O(B)         | O(B)       | Scans all blob indexes             |
| Close              | O(1)         | O(1)       | -                                  |

### Space Complexity

| Component           | Size                          |
|---------------------|-------------------------------|
| File header         | 32 bytes                      |
| Blob index table    | blobCount × 4 bytes           |
| Segment overhead    | 8 bytes per blob (header)     |
| Unused space        | Up to (segmentSize - 8) bytes per blob |

### Memory Usage (JVM)

| Component           | Size                              |
|---------------------|-----------------------------------|
| Index locks array   | blobCount × ~32 bytes             |
| Segment locks array | segmentCount × ~32 bytes          |
| Memory-mapped index | blobCount × 4 bytes (off-heap)    |
| Used segments BitSet| segmentCount / 8 bytes            |
| Thread-local buffer | 32 bytes per thread               |

**Example (blobCount=1024, 1000 segments, 10 threads):**
```
Index locks:     1024 × 32 = 32 KB
Segment locks:   1000 × 32 = 32 KB
Memory-mapped:   4 KB (off-heap)
Used segments:   1000 / 8 = 125 bytes
Thread buffers:  10 × 32 = 320 bytes
Total:           ~64.5 KB (on-heap) + 4 KB (off-heap)
```

---

## Appendix D: Compression Ratios

Typical ZSTD compression ratios for Minecraft-style chunk data:

| Data Type               | Original Size | Compressed Size | Ratio  |
|-------------------------|---------------|-----------------|--------|
| Empty/Air chunks        | ~65 KB        | ~100 bytes      | 99.8%  |
| Mostly empty chunks     | ~65 KB        | ~500 bytes      | 99.2%  |
| Terrain chunks          | ~65 KB        | ~5 KB           | 92.3%  |
| Mixed/complex chunks    | ~65 KB        | ~15 KB          | 76.9%  |
| Random/noisy data       | ~65 KB        | ~60 KB          | 7.7%   |

Compression level 3 provides good balance between speed and ratio.

---

## Revision History

| Version | Date       | Changes                                    |
|---------|------------|--------------------------------------------|
| 1.0     | 2026-01-21 | Initial specification based on implementation analysis |

---

**End of Specification**


DECOMPRESS.py
```python
import compression.zstd
import base64

data = b'data here'

raw = base64.b64decode(data)
print(raw[:100])

decompressed = compression.zstd.decompress(raw)
print(decompressed)

with open("output.bin", 'wb') as file:
    file.write(decompressed)
```