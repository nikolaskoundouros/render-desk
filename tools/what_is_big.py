"""What is making this .blend so large?

Open the scene in Blender, go to the Scripting tab, open this file and press Run.
It prints a report in the console. Nothing is changed or saved.

Why it matters: uploading 300 MB on a slow line takes about an hour. Most of that
is usually texture data that is far larger than the final video can show.
"""
import os

import bpy


def mb(n):
    return f"{n / 1048576:8.1f} MB"


def main():
    path = bpy.data.filepath
    print("\n" + "=" * 68)
    print("WHAT IS BIG IN THIS FILE")
    print("=" * 68)
    if path and os.path.exists(path):
        size = os.path.getsize(path)
        print(f"File on disk: {mb(size)}   {os.path.basename(path)}")
        print(f"Saved compressed: {'yes' if is_compressed(path) else 'NO  <-- see step 1 below'}")
    print()

    images, linked = [], []
    for image in bpy.data.images:
        width, height = image.size
        if image.packed_file:
            # Packed means its bytes are inside the .blend, which is what you upload.
            images.append((image.packed_file.size, width, height, image.name))
        elif image.filepath:
            linked.append((width, height, image.name))
    images.sort(reverse=True)

    packed_total = sum(i[0] for i in images)
    print(f"Images: {len(images)}, of which packed into the file: {mb(packed_total)}")
    print()
    print(f"  {'packed':>10}  {'pixels':>11}  name")
    print("  " + "-" * 60)
    for packed, width, height, name in images[:25]:
        print(f"  {mb(packed)}  {width:5d}x{height:<5d}  {name[:40]}")
    if len(images) > 25:
        print(f"  ...and {len(images) - 25} more")

    if linked:
        print()
        print(f"  {len(linked)} image(s) are NOT packed. Those will be missing when it")
        print("  renders, unless you do File > External Data > Automatically Pack Resources.")

    big = [i for i in images if max(i[1], i[2]) > 2048]
    if big:
        saved = sum(i[0] for i in big) * 0.94   # 4K -> 2K is roughly a 16x reduction
        print()
        print(f"  {len(big)} image(s) are larger than 2K, holding {mb(sum(i[0] for i in big))}.")
        print(f"  Halving those twice would save roughly {mb(saved)}.")

    verts = sum(len(m.vertices) for m in bpy.data.meshes)
    print()
    print(f"Meshes: {len(bpy.data.meshes)}, {verts:,} vertices total")
    heavy = sorted(bpy.data.meshes, key=lambda m: -len(m.vertices))[:5]
    for mesh in heavy:
        if len(mesh.vertices) > 10000:
            print(f"  {len(mesh.vertices):>10,} verts  {mesh.name[:40]}")

    print()
    print("=" * 68)
    print("WHAT TO DO, IN ORDER")
    print("=" * 68)
    print("1. File > Save As, and tick 'Compress' on the left. Costs nothing, often")
    print("   shrinks the file a lot, and changes nothing about the render.")
    print()
    print("2. Any texture bigger than 2K that never fills the screen is wasted: the")
    print("   video is 1080 wide, so a background object shows a few hundred pixels")
    print("   of it at most. Keep the big ones ONLY for surfaces the camera pushes")
    print("   into close up.")
    print()
    print("3. Send Nick this report before changing anything, so he can say which")
    print("   textures are safe to shrink.")
    print("=" * 68 + "\n")


def is_compressed(path):
    with open(path, "rb") as handle:
        head = handle.read(4)
    return not head.startswith(b"BLEN")


if __name__ == "__main__":
    main()
