# -*- coding: utf-8 -*-
# 球フィールドの効果を可視化: 平面グリッド + 中央の球フィールドで Random(Z) を変調。
# フィールド内のクローンだけ持ち上がり、外は平ら → 滑らかな「山」ができる。
# 実行: blender.exe --background --factory-startup --python tests/render_field.py
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
    bmesh.ops.create_cube(bm, size=0.28)
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
    cam.location = (8.0, -8.0, 6.5)
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
    scene.render.resolution_y = 360
    scene.render.image_settings.file_format = 'PNG'


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
    # 平面グリッド(Z=1)11x11、間隔50cm → 5m四方
    p.mode = 'GRID'
    p.count_x = 11
    p.count_y = 11
    p.count_z = 1
    p.spacing_x = p.spacing_y = 50.0
    # Random モジュレータ(Z 持ち上げ・フィールドでゲート)
    m = p.modulators.add()
    m.mtype = 'RANDOM'
    m.seed = 3
    m.pos = (0.0, 0.0, 200.0)
    m.use_field = True
    # 球フィールド(中央・半径200cm・滑らか)
    fo = replicator.ensure_field(e)
    p.field_enable = True
    p.field_type = 'SPHERE'
    p.field_radius = 200.0
    p.field_falloff = 1.0
    fo.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    setup_scene(e)
    eng = try_engine(bpy.context.scene, ['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'])
    log("engine:", eng, "instances:",
        sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance))
    bpy.context.scene.render.filepath = BENCH + r"\render_field.png"
    bpy.ops.render.render(write_still=True)
    log("saved bench/render_field.png")
    log("DONE")


main()
