# -*- coding: utf-8 -*-
# v0.8.1 テスト: 数のセーフティ(最大100/解除で1000)+ 散布率を1000%まで
# 実行: blender.exe --background --factory-startup --python tests/test_phase15.py
import bpy
import sys
import bmesh

SRC = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import importlib
import replicator
importlib.reload(replicator)

_fails = []


def log(*a):
    print("[TEST]", *a)
    sys.stdout.flush()


def check(name, cond):
    log(("PASS" if cond else "FAIL"), name)
    if not cond:
        _fails.append(name)


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for c in list(bpy.data.collections):
        if c is not bpy.context.scene.collection:
            bpy.data.collections.remove(c)


def mk_cube(name, size):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def mk_plane(name, size):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=size)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def count_instances():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return sum(1 for i in deps.object_instances if i.is_instance)


def positions():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    out = []
    for i in deps.object_instances:
        if i.is_instance:
            t = i.matrix_world.translation
            out.append((round(t.x, 3), round(t.y, 3), round(t.z, 3)))
    return out


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()

    src = mk_cube("src", 0.2)
    e = replicator.create_replicator(bpy.context, [src])
    p = e.replicator

    # ===== A. 数のセーフティ(クランプ) =====
    check("セーフティ既定ON", p.count_safety is True)

    # 安全ON: 500 を入れても 100 にクランプ
    p.count_safety = True
    p.count_x = 500
    log("safety ON, set 500 ->", p.count_x)
    check("安全ONで500→100にクランプ", p.count_x == 100)

    # ちょうど100は通る
    p.count_x = 100
    check("安全ONで100はそのまま", p.count_x == 100)

    # 安全OFF: 500 を許容
    p.count_safety = False
    p.count_x = 500
    log("safety OFF, set 500 ->", p.count_x)
    check("安全OFFで500を許容", p.count_x == 500)

    # 安全OFFでも上限1000(1500→1000)
    p.count_x = 1500
    log("safety OFF, set 1500 ->", p.count_x)
    check("安全OFFでも最大1000にクランプ", p.count_x == 1000)

    # 安全を再ONにすると既存の大きい数もクランプされる
    p.count_x = 800
    p.count_safety = True
    log("re-enable safety with 800 ->", p.count_x)
    check("セーフティ再ONで既存800→100", p.count_x == 100)

    # リニアで実数も反映(安全OFF, 300個)
    p.mode = 'LINEAR'
    p.count_safety = False
    p.count_x = 300
    check("安全OFF・リニア300個が生成", count_instances() == 300)

    # ===== B. 散布率を1000%まで(基準=count_x) =====
    clear()
    plane = mk_plane("plane", 2.0)
    src2 = mk_cube("src2", 0.2)
    e2 = replicator.create_replicator(bpy.context, [src2])
    p2 = e2.replicator
    p2.mode = 'MESH'
    p2.mesh_object = plane
    p2.mesh_source = 'SURFACE'
    p2.count_x = 100                 # 基準100(安全ONのまま)
    p2.scatter_seed = 3

    p2.scatter_amount = 100.0
    n100 = count_instances()
    pos100 = set(positions())
    check("散布率100%=基準どおり100個", n100 == 100)

    p2.scatter_amount = 300.0
    n300 = count_instances()
    log("amount 300% ->", n300)
    check("散布率300%で300個(基準の3倍)", n300 == 300)

    p2.scatter_amount = 1000.0
    n1000 = count_instances()
    log("amount 1000% ->", n1000)
    check("散布率1000%で1000個(基準の10倍)", n1000 == 1000)

    # 率を上げても既存点は動かない(100%の集合 ⊆ 1000%の集合)
    pos1000 = set(positions())
    check("増やしても既存点は不動(100%⊆1000%)", pos100.issubset(pos1000))

    # 上限1000%を超えて入れてもクランプ(プロパティ範囲)
    p2.scatter_amount = 5000.0
    log("set 5000% ->", round(p2.scatter_amount, 1))
    check("散布率は最大1000%にクランプ", abs(p2.scatter_amount - 1000.0) < 0.01)

    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
