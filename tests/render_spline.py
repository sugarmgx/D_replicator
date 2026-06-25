# -*- coding: utf-8 -*-
# スプラインモードの可視化: 螺旋カーブに沿って円錐を「接線に揃える」で等間隔配置。
# 円錐がカーブの進行方向を向く = C4D スプラインモードの典型(パスに沿うクローン)。
# 実行: blender.exe --background --factory-startup --python tests/render_spline.py
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
    print("[TEST]", *a)
    sys.stdout.flush()


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)


def mk_cone(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    # 既定で軸 +Z。揃え軸 Z(接線)で先端が進行方向を向く
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12,
                          radius1=0.16, radius2=0.0, depth=0.5)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def mk_helix(name):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sp = cu.splines.new('POLY')
    pts = []
    steps = 80
    for k in range(steps):
        t = (k / (steps - 1)) * 4.0 * math.pi
        pts.append((math.cos(t) * 2.2, math.sin(t) * 2.2, t * 0.28 - 1.8))
    sp.points.add(len(pts) - 1)
    for i, c in enumerate(pts):
        sp.points[i].co = (c[0], c[1], c[2], 1.0)
    o = bpy.data.objects.new(name, cu)
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
    cam.location = (8.5, -8.5, 5.5)
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

    cone = mk_cone("cone")
    helix = mk_helix("helix")
    helix.hide_render = True              # カーブ自体は写さない

    e = replicator.create_replicator(bpy.context, [cone])
    p = e.replicator
    p.mode = 'SPLINE'
    p.spline_object = helix
    p.count_x = 44
    p.spline_align = True
    p.align_axis = 'Z'                    # 円錐の先端(+Z)を接線へ
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    setup_scene(e)
    eng = try_engine(bpy.context.scene, ['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'])
    n = sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance)
    log("engine:", eng, "instances:", n)
    bpy.context.scene.render.filepath = BENCH + r"\render_spline.png"
    bpy.ops.render.render(write_still=True)
    log("saved bench/render_spline.png")
    log("DONE")


main()
