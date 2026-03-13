import random

seed = 1768358471
random.seed(seed)
print(f"Seed: {seed}")

data = [random.randint(0, 1) for _ in range(100)]

print("First 30 bits:")
print(data[:30])

# Reconstruct expected packets (PACK_ORDER=0)
print("\nExpected Packets:")
packets = []
for i in range(0, len(data), 2):
    if i+1 < len(data):
        a = data[i]
        b = data[i+1]
        val = (a << 1) | b
        packets.append(val)
        print(f"#{i//2 + 1}: {val} (inputs {a}, {b})")
