# -*- coding: utf-8 -*-
# フィールド角度の可視化: 箱フィールドを Z 45°回転 → 影響範囲が「ダイヤ型」になる
# (render_field_box.png は 0°=四角。比べると回転が効いているのが分かる)
# 実行: blender.exe --background --factory-startup --python tests/render_field_angle.py
import bpy
import sys
import math
import bmesh

SRC = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import importlib
import replicator
importlib.reload(replicator)
BENCH = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\bench"


def log(*a):
    print("[TEST]", *a); sys.stdout.flush()


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def mk_cube(name, size=0.28):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.mode = 'GRID'
    p.count_x = 11
    p.count_y = 11
    p.count_z = 1
    p.spacing_x = p.spacing_y = 50.0
    m = p.modulators.add()
    m.mtype = 'RANDOM'
    m.seed = 3
    m.pos = (0.0, 0.0, 200.0)
    m.use_field = True
    fo = replicator.ensure_field(e)
    p.field_enable = True
    p.field_type = 'BOX'
    p.field_radius = 170.0
    p.field_falloff = 0.4
    fo.location = (0.0, 0.0, 0.0)
    fo.rotation_euler = (0.0, 0.0, math.radians(45.0))   # ← Z 45°回転(ダイヤ型に)
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    scene = bpy.context.scene
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, 12.0)        # 真上から(回転=ダイヤが分かりやすい)
    cam.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
    sun.data.energy = 4.0
    scene.collection.objects.link(sun)
    sun.rotation_euler = (0.5, 0.2, 0.3)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("W")
    scene.world.use_nodes = False
    scene.world.color = (0.05, 0.05, 0.06)
    scene.render.resolution_x = 420
    scene.render.resolution_y = 420
    scene.render.image_settings.file_format = 'PNG'
    try:
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    except Exception:
        scene.render.engine = 'BLENDER_EEVEE'
    log("instances:", sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance),
        "field rot Z = 45deg")
    scene.render.filepath = BENCH + r"\render_field_angle.png"
    bpy.ops.render.render(write_still=True)
    log("saved bench/render_field_angle.png")
    log("DONE")


main()
