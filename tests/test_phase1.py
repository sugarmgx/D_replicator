# -*- coding: utf-8 -*-
# Phase 1 v0.1 自己回帰テスト(headless)
# 実行: blender.exe --background --factory-startup --python tests/test_phase1.py
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


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()

    # シーンを空に
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)

    # 複製元キューブを手動作成(op コンテキスト依存を避ける)
    me = bpy.data.meshes.new("srcCube")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    cube = bpy.data.objects.new("srcCube", me)
    bpy.context.collection.objects.link(cube)
    bpy.context.view_layer.objects.active = cube
    log("source:", cube.name)

    empty = replicator.create_replicator(bpy.context, [cube])
    log("controller:", empty.name, empty.type, "is_rep:", empty.replicator.is_replicator)
    log("children:", [c.name for c in empty.children])
    disp = replicator.get_display(empty)
    log("display verts:", len(disp.data.vertices))

    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    # DepsgraphObjectInstance はイテレーション中のみ有効 → その場で値を抜く
    xs, ys, zs = set(), set(), set()
    count = 0
    for i in deps.object_instances:
        if i.is_instance:
            count += 1
            t = i.matrix_world.translation
            xs.add(round(t.x, 3))
            ys.add(round(t.y, 3))
            zs.add(round(t.z, 3))
    log("INSTANCE_COUNT:", count)
    xs = sorted(xs)
    ys = sorted(ys)
    zs = sorted(zs)
    log("X:", xs)
    log("Y:", ys)
    log("Z:", zs)

    ok = (count == 27 and xs == [-2.0, 0.0, 2.0]
          and ys == [-2.0, 0.0, 2.0] and zs == [-2.0, 0.0, 2.0])
    log("RESULT:", "PASS" if ok else "FAIL")

    # 数変更も反映されるか
    empty.replicator.count_x = 5
    deps.update()
    c2 = sum(1 for i in deps.object_instances if i.is_instance)
    log("after count_x=5 -> INSTANCE_COUNT:", c2, "(expect 45)")


main()
