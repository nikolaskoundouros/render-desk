"""Build a throwaway scene for the end-to-end check. Runs inside Blender.

blender -b --factory-startup -noaudio --python make_test_blend.py -- out.blend [--broken]
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out = argv[0]
broken = "--broken" in argv
no_camera = "--no-camera" in argv

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 4
scene.render.resolution_x = 64
scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
scene.render.fps = 24
scene.frame_start = 1
scene.frame_end = 3

bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
cube = bpy.context.active_object
cube.keyframe_insert("rotation_euler", frame=1)
cube.rotation_euler[2] = 1.0
cube.keyframe_insert("rotation_euler", frame=3)

light = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", type="SUN"))
scene.collection.objects.link(light)
light.location = (3, -3, 5)

if not no_camera:
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(cam)
    cam.location = (0, -6, 2)
    cam.rotation_euler = (1.2, 0, 0)
    scene.camera = cam

if broken:
    # An image that points at a file which does not exist: exactly the
    # unpacked-texture case the preflight gate has to catch.
    image = bpy.data.images.new("missing_tex", 8, 8)
    image.filepath = "//textures/does_not_exist_9f3a.png"
    image.source = "FILE"
    material = bpy.data.materials.new("m")
    material.use_nodes = True
    tex = material.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = image
    bsdf = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    cube.data.materials.append(material)

bpy.ops.wm.save_as_mainfile(filepath=out)
