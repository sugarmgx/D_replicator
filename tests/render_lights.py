# -*- coding: utf-8 -*-
# ライト複製の可視化: 暖色のポイントライトを円形に8個クローン → 床に光のリング。
# ライトは GN インスタンスとして実際に照らす(EEVEE Next)。
# 実行: blender.exe --background --factory-startup --python tests/render_lights.py
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


def mk_floor():
    me = bpy.data.meshes.new("floor")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=8.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("floor", me)
    bpy.context.scene.collection.objects.link(o)
    mat = bpy.data.materials.new("floor")
    mat.use_nodes = False
    mat.diffuse_color = (0.8, 0.8, 0.82, 1)
    o.data.materials.append(mat)
    return o


def mk_pillar(name, x, y):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.5, radius2=0.5, depth=2.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    o.location = (x, y, 1.0)
    bpy.context.scene.collection.objects.link(o)
    return o


def mk_warm_light(name):
    ld = bpy.data.lights.new(name, 'POINT')
    ld.energy = 1200.0
    ld.color = (1.0, 0.6, 0.3)            # 暖色
    ld.shadow_soft_size = 0.3
    o = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(o)
    return o


def setup_scene(e):
    scene = bpy.context.scene
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    cam.location = (9.5, -9.5, 7.0)
    con = cam.constraints.new('TRACK_TO')
    con.target = e
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'
    scene.camera = cam
    if scene.world is None:
        scene.world = bpy.data.worlds.new("W")
    scene.world.use_nodes = False
    scene.world.color = (0.02, 0.02, 0.03)   # 暗い環境 → 照明はクローンライトのみ
    scene.render.resolution_x = 480
    scene.render.resolution_y = 380
    scene.render.image_settings.file_format = 'PNG'
    for eid in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        try:
            scene.render.engine = eid
            break
        except Exception:
            continue
    return scene.render.engine


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    mk_floor()
    # 光を受ける柱を数本
    for (x, y) in [(-2.5, 0), (2.5, 0), (0, -2.5), (0, 2.5)]:
        mk_pillar("pillar", x, y)

    light = mk_warm_light("warm")
    e = replicator.create_replicator(bpy.context, [light])
    e.location = (0.0, 0.0, 2.5)             # リングを床の上へ
    p = e.replicator
    p.mode = 'CIRCLE'
    p.count_x = 8
    p.radius = 350.0                          # 半径3.5m
    p.radial_plane = 'XY'
    p.radial_arc = 360.0
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    eng = setup_scene(e)
    n = sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance)
    log("engine:", eng, "light instances:", n, "(expect 8)")
    bpy.context.scene.render.filepath = BENCH + r"\render_lights.png"
    bpy.ops.render.render(write_still=True)
    log("saved bench/render_lights.png")
    log("DONE")


main()
