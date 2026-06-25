# -*- coding: utf-8 -*-
# v0.3.4 テスト: 出力のジオメトリ化(Realize)+ 通常モディファイヤ(Simple Deform)が全体に効くか
# 実行: blender.exe --background --factory-startup --python tests/test_phase5.py
import bpy
import sys
import bmesh

SRC = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import importlib
import replicator
importlib.reload(replicator)


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
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def count_instances():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return sum(1 for i in deps.object_instances if i.is_instance)


def eval_mesh_stats(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    oe = obj.evaluated_get(deps)
    me = oe.to_mesh()
    n = len(me.vertices)
    mx = max((abs(v.co.x) for v in me.vertices), default=0.0)
    oe.to_mesh_clear()
    return n, round(mx, 3)


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()

    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    disp = replicator.get_display(e)

    log("realize OFF instances:", count_instances(), "(expect 27 = インスタンス)")

    e.replicator.realize_output = True
    log("realize ON instances:", count_instances(), "(expect 0 = 実メッシュ化)")
    n, mx = eval_mesh_stats(disp)
    log("realize ON mesh verts:", n, "(expect 216 = 27*8)")

    # Replicator GN の後ろに Simple Deform を積む → 全体に効くか
    md = disp.modifiers.new("Twist", 'SIMPLE_DEFORM')
    md.deform_method = 'TWIST'
    md.deform_axis = 'Z'
    md.angle = 0.0
    _, x0 = eval_mesh_stats(disp)
    md.angle = 2.0
    _, x2 = eval_mesh_stats(disp)
    log("Simple Deform twist x-extent angle0:", x0, "angle2:", x2,
        "->", "PASS (効いた)" if x0 != x2 else "FAIL")
    log("DONE")


main()
