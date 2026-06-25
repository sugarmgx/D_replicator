# -*- coding: utf-8 -*-
# 面上ランダム散布の可視化: Suzanne の表面に小立方体を面積重みで散布(法線揃え)。
# 散布率 70% で「まばらにびっしり」。シードで当たり探し、率でアニメ密度。
# 実行: blender.exe --background --factory-startup --python tests/render_scatter.py
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


def mk_box(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.12)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def mk_monkey(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_monkey(bm)
    bmesh.ops.scale(bm, vec=(2.0, 2.0, 2.0), verts=bm.verts)
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


def setup_scene(e):
    scene = bpy.context.scene
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    cam.location = (7.0, -7.0, 5.0)
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
    scene.world.color = (0.05, 0.05, 0.06)
    scene.render.resolution_x = 480
    scene.render.resolution_y = 420
    scene.render.image_settings.file_format = 'PNG'


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    box = mk_box("box")
    monkey = mk_monkey("monkey")
    monkey.hide_render = True             # 土台は写さない(散布だけ見せる)

    e = replicator.create_replicator(bpy.context, [box])
    p = e.replicator
    p.mode = 'MESH'
    p.mesh_object = monkey
    p.mesh_source = 'SURFACE'
    p.count_x = 1500
    p.scatter_amount = 70.0              # 0-100% の率(=1050個表示)
    p.scatter_seed = 5
    p.mesh_align = True
    p.align_axis = 'Z'
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    setup_scene(e)
    eng = try_engine(bpy.context.scene, ['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'])
    n = sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance)
    log("engine:", eng, "instances:", n, "(= 1500 * 70%)")
    bpy.context.scene.render.filepath = BENCH + r"\render_scatter.png"
    bpy.ops.render.render(write_still=True)
    log("saved bench/render_scatter.png")
    log("DONE")


main()
