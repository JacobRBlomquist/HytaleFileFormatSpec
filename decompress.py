import compression.zstd
import base64

data = b'data here'

raw = base64.b64decode(data)
print(raw[:100])

decompressed = compression.zstd.decompress(raw)
print(decompressed)

with open("output.bin", 'wb') as file:
    file.write(decompressed)