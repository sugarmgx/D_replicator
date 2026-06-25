# -*- coding: utf-8 -*-
# メッシュモードの可視化: アイコスフィアの各面の中心に円錐を「法線に揃える」で配置。
# 円錐の先端が球面から外向きに生える = C4D オブジェクトモードの典型的な絵。
# 実行: blender.exe --background --factory-startup --python tests/render_mesh.py
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


def mk_cone(name):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    # 既定で軸は +Z。法線揃え(+Z→法線)で先端が外を向く
    bmesh.ops.create_cone(bm, cap_ends=True, segments=14,
                          radius1=0.18, radius2=0.0, depth=0.55)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def mk_icosphere(name, radius, subdiv):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
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
    scene.render.resolution_y = 360
    scene.render.image_settings.file_format = 'PNG'


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    cone = mk_cone("cone")
    ref = mk_icosphere("refSphere", 2.0, 2)     # 半径2m・80面
    ref.hide_render = True                       # 参照自体は写さない(クローンだけ見せる)

    e = replicator.create_replicator(bpy.context, [cone])
    p = e.replicator
    p.mode = 'MESH'
    p.mesh_object = ref
    p.mesh_source = 'FACES'
    p.mesh_align = True
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    setup_scene(e)
    eng = try_engine(bpy.context.scene, ['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'])
    n = sum(1 for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance)
    log("engine:", eng, "instances:", n, "(= 球の面数)")
    bpy.context.scene.render.filepath = BENCH + r"\render_mesh.png"
    bpy.ops.render.render(write_still=True)
    log("saved bench/render_mesh.png")
    log("DONE")


main()
