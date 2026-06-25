# -*- coding: utf-8 -*-
# v0.3.2 テスト: 複製元の Replicator からの操作(表示トグル/追加/削除)
# 実行: blender.exe --background --factory-startup --python tests/test_phase4.py
import bpy
import sys
import bmesh
from collections import Counter

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


def tally():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    t = Counter()
    for i in deps.object_instances:
        if i.is_instance and i.object:
            t[i.object.name] += 1
    return t


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()

    clear()
    cube = mk_cube("cube")
    e = replicator.create_replicator(bpy.context, [cube])
    def in_vl(o):
        # シーンコレクション所属 = ビューレイヤーに出る(view_layer.objects は headless でキャッシュが古い)
        return o.name in bpy.context.scene.collection.objects

    log("default visible:", in_vl(cube), "(expect False = 隠れている)")
    e.replicator.show_sources = True
    log("show=True visible:", in_vl(cube), "(expect True)")
    e.replicator.show_sources = False
    log("show=False visible:", in_vl(cube), "(expect False)")

    # 複製元を追加(親子付け + 更新)
    cube2 = mk_cube("cube2")
    cube2.parent = e
    replicator.update_replicator(e)
    srcs = [c.name for c in e.children if not c.get(replicator.DISPLAY_TAG)]
    log("sources after add:", srcs, "(expect cube, cube2)")
    t = tally()
    log("distribution:", {k: t.get(k, 0) for k in ("cube", "cube2")},
        "total:", sum(t.get(k, 0) for k in ("cube", "cube2")), "(expect 27)")

    # 複製元を外す(オペレータ)
    bpy.context.view_layer.objects.active = e
    try:
        bpy.ops.object.replicator_remove_source(name="cube2")
        srcs2 = [c.name for c in e.children if not c.get(replicator.DISPLAY_TAG)]
        log("after remove:", srcs2, "/ cube2 back in view layer:", in_vl(bpy.data.objects['cube2']),
            "(expect [cube], True)")
    except Exception as ex:
        log("remove op failed:", repr(ex))

    log("DONE")


main()
