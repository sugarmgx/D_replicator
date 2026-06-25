# -*- coding: utf-8 -*-
# レンダー再現: EEVEE 静止画 + アニメ(ハンドラがレンダー中に走る)で消えないか
# 実行: blender.exe --background --factory-startup --python tests/test_render.py
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
    print("[TEST]", *a)
    sys.stdout.flush()


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def mk_cube(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.7)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def try_engine(scene, ids):
    for eid in ids:
        try:
            scene.render.engine = eid
            return scene.render.engine
        except Exception:
            continue
    return None


def count():
    d = bpy.context.evaluated_depsgraph_get()
    d.update()
    return sum(1 for i in d.object_instances if i.is_instance)


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    scene = bpy.context.scene

    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    cam.location = (9.0, -9.0, 6.0)
    con = cam.constraints.new('TRACK_TO')
    con.target = e
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    scene.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", 'SUN'))
    sun.data.energy = 4.0
    scene.collection.objects.link(sun)
    sun.rotation_euler = (0.6, 0.2, 0.3)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("W")
    scene.world.use_nodes = False
    scene.world.color = (0.05, 0.05, 0.05)

    scene.render.resolution_x = 320
    scene.render.resolution_y = 320
    scene.render.image_settings.file_format = 'PNG'

    log("viewport instances:", count())

    eng = try_engine(scene, ['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'])
    log("eevee engine:", eng)
    scene.render.filepath = BENCH + r"\render_eevee.png"
    bpy.ops.render.render(write_still=True)
    log("eevee still saved")

    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.frame_start = 1
    scene.frame_end = 3
    scene.render.filepath = BENCH + r"\anim\f"
    bpy.ops.render.render(animation=True)
    log("anim saved (f0001..f0003)")
    log("after-anim viewport instances:", count())
    log("DONE")


main()
