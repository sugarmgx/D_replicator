# -*- coding: utf-8 -*-
# 新機能の可視化: (1) 箱フィールド×Random (2) フィールドが段階トランスフォームに効く
# 実行: blender.exe --background --factory-startup --python tests/render_field_types.py
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


def setup_camera(target, loc):
    scene = bpy.context.scene
    cam = bpy.data.objects.get("Cam")
    if cam is None:
        cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
        scene.collection.objects.link(cam)
        con = cam.constraints.new('TRACK_TO')
        con.track_axis = 'TRACK_NEGATIVE_Z'
        con.up_axis = 'UP_Y'
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
        try:
            scene.render.engine = 'BLENDER_EEVEE_NEXT'
        except Exception:
            scene.render.engine = 'BLENDER_EEVEE'
    cam.location = loc
    cam.constraints[0].target = target
    scene.camera = cam


def render(path):
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    log("saved", path)


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()

    # --- (1) 箱フィールド × Random(平面11x11) ---
    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.mode = 'GRID'; p.count_x = 11; p.count_y = 11; p.count_z = 1
    p.spacing_x = p.spacing_y = 50.0
    m = p.modulators.add()
    m.mtype = 'RANDOM'; m.seed = 3; m.pos = (0.0, 0.0, 200.0); m.use_field = True
    fo = replicator.ensure_field(e)
    p.field_enable = True
    p.field_type = 'BOX'; p.field_radius = 180.0; p.field_falloff = 0.6
    fo.location = (0.0, 0.0, 0.0)
    bpy.context.view_layer.update(); replicator.apply_transforms(e)
    setup_camera(e, (8.0, -8.0, 6.5))
    render(BENCH + r"\render_field_box.png")

    # --- (2) フィールドが「段階トランスフォーム」に効く(線状に並べ、中央だけ盛り上げ) ---
    clear()
    cube = mk_cube("cube", size=0.22)
    e = replicator.create_replicator(bpy.context, [cube])
    p = e.replicator
    p.mode = 'LINEAR'; p.count_x = 21
    p.spacing_x = 30.0; p.spacing_y = 0.0; p.spacing_z = 0.0   # X方向に一列
    p.step_normalized = True
    p.step_pos = (0.0, 0.0, 220.0)     # 段階で Z 持ち上げ(端ほど高い)
    fo = replicator.ensure_field(e)
    p.field_enable = True
    p.step_use_field = True            # ← 段階トランスフォームをフィールドで絞る
    p.field_type = 'SPHERE'; p.field_radius = 150.0; p.field_falloff = 1.0
    fo.location = (3.0, 0.0, 0.0)       # 列の中央あたり(X=0..6m の真ん中)
    bpy.context.view_layer.update(); replicator.apply_transforms(e)
    setup_camera(e, (3.0, -9.0, 3.0))
    render(BENCH + r"\render_field_step.png")
    log("DONE")


main()
