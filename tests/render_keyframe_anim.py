# -*- coding: utf-8 -*-
# キーフレームの可視化: フィールド位置をキーフレーム → クローンの乱れが掃いて動く
# 実行: blender.exe --background --factory-startup --python tests/render_keyframe_anim.py
import bpy
import sys
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
    p.count_x = 13
    p.count_y = 13
    p.count_z = 1
    p.spacing_x = p.spacing_y = 45.0
    m = p.modulators.add()
    m.mtype = 'RANDOM'
    m.seed = 4
    m.pos = (0.0, 0.0, 220.0)
    m.use_field = True
    fo = replicator.ensure_field(e)
    p.field_enable = True
    p.field_type = 'SPHERE'
    p.field_radius = 160.0
    p.field_falloff = 1.0

    # フィールド X 位置をキーフレーム(左 → 右へ掃く)
    sc = bpy.context.scene
    sc.frame_start = 1
    sc.frame_end = 10
    fo.location = (-2.6, 0.0, 0.0)
    fo.keyframe_insert("location", frame=1)
    fo.location = (2.6, 0.0, 0.0)
    fo.keyframe_insert("location", frame=10)

    # シーン
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    cam.location = (0.0, -9.0, 7.5)
    con = cam.constraints.new('TRACK_TO')
    con.target = e
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    sc.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
    sun.data.energy = 4.0
    sc.collection.objects.link(sun)
    sun.rotation_euler = (0.6, 0.2, 0.3)
    if sc.world is None:
        sc.world = bpy.data.worlds.new("W")
    sc.world.use_nodes = False
    sc.world.color = (0.05, 0.05, 0.06)
    sc.render.resolution_x = 440
    sc.render.resolution_y = 320
    sc.render.image_settings.file_format = 'PNG'
    try:
        sc.render.engine = 'BLENDER_EEVEE_NEXT'
    except Exception:
        sc.render.engine = 'BLENDER_EEVEE'

    for f in (1, 5, 10):
        sc.frame_set(f)                     # ← frame_change ハンドラが再計算
        sc.render.filepath = BENCH + (r"\kf_f%02d.png" % f)
        bpy.ops.render.render(write_still=True)
        log("saved kf_f%02d.png (field x=%.2f)" % (f, fo.location.x))
    log("DONE")


main()
