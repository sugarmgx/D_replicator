# -*- coding: utf-8 -*-
# モジュレータ・スタックの可視化: Step(スケール勾配) + Random(回転ばらつき) を積む
# 実行: blender.exe --background --factory-startup --python tests/render_stack.py
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


def mk_cube(name, size=0.3):
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
    p.count_x = 8
    p.count_y = 8
    p.count_z = 1
    p.spacing_x = p.spacing_y = 60.0
    # スタック: ① Step(スケール勾配で奥ほど大きく) ② Random(回転ばらつき)
    m_step = p.modulators.add()
    m_step.mtype = 'STEP'
    m_step.name = "Step-Scale"
    m_step.scale = 1.6            # 端まで ×(1+1.6)=×2.6
    m_step.normalized = True
    m_rand = p.modulators.add()
    m_rand.mtype = 'RANDOM'
    m_rand.name = "Rand-Rot"
    m_rand.rot = (40.0, 40.0, 40.0)
    m_rand.seed = 5
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    scene = bpy.context.scene
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    cam.location = (7.5, -7.5, 6.0)
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
    try:
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    except Exception:
        scene.render.engine = 'BLENDER_EEVEE'
    cnt = sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance)
    log("instances:", cnt, "modulators:", [m.name for m in p.modulators])
    scene.render.filepath = BENCH + r"\render_stack.png"
    bpy.ops.render.render(write_still=True)
    log("saved bench/render_stack.png")
    log("DONE")


main()
