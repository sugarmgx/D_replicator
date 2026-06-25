# -*- coding: utf-8 -*-
# v0.9 テスト: ライトを複製元にできる(GN インスタンスとして実際に照らす)
# 実行: blender.exe --background --factory-startup --python tests/test_phase17.py
import bpy
import sys
import os
import bmesh

SRC = r"C:\Users\asupe\OneDrive\Documents\claude_code\blender_mograph_addon\src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import importlib
import replicator
importlib.reload(replicator)
TMP = bpy.app.tempdir          # 輝度測定用の一時レンダー(bench は汚さない)

_fails = []


def log(*a):
    print("[TEST]", *a)
    sys.stdout.flush()


def check(name, cond, extra=""):
    log(("PASS" if cond else "FAIL"), "-", name, extra)
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


def mk_floor():
    me = bpy.data.meshes.new("floor")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=10.0)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new("floor", me)
    bpy.context.scene.collection.objects.link(o)
    mat = bpy.data.materials.new("white")
    mat.use_nodes = False
    mat.diffuse_color = (1, 1, 1, 1)
    o.data.materials.append(mat)
    return o


def mk_point_light(name, energy=2000.0):
    ld = bpy.data.lights.new(name, 'POINT')
    ld.energy = energy
    o = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(o)
    return o


def setup_render():
    sc = bpy.context.scene
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    sc.collection.objects.link(cam)
    cam.location = (0, 0, 14)
    cam.rotation_euler = (0, 0, 0)
    sc.camera = cam
    if sc.world is None:
        sc.world = bpy.data.worlds.new("W")
    sc.world.use_nodes = False
    sc.world.color = (0, 0, 0)
    sc.render.resolution_x = 120
    sc.render.resolution_y = 120
    sc.render.image_settings.file_format = 'PNG'
    for eid in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
        try:
            sc.render.engine = eid
            break
        except Exception:
            continue
    return sc.render.engine


def brightness(path):
    img = bpy.data.images.load(path)
    px = list(img.pixels)
    s = sum(px[i] + px[i + 1] + px[i + 2] for i in range(0, len(px), 4))
    bpy.data.images.remove(img)
    return s / max(len(px) // 4 * 3, 1)


def n_instances():
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    return sum(1 for i in deps.object_instances if i.is_instance)


def main():
    try:
        replicator.unregister()
    except Exception:
        pass
    replicator.register()
    clear()
    eng = setup_render()
    log("engine:", eng)
    mk_floor()

    # 暗いベースライン(ライト無し)
    bpy.context.scene.render.filepath = os.path.join(TMP, "_p17_dark.png")
    bpy.ops.render.render(write_still=True)
    b_dark = brightness(bpy.context.scene.render.filepath)
    log("baseline dark:", round(b_dark, 3))

    # ライトを複製元に → グリッド 2x2x1 = 4個のライトを床の上に
    light = mk_point_light("L", 2500.0)
    e = replicator.create_replicator(bpy.context, [light])
    e.location = (0.0, 0.0, 6.0)         # グリッドを床の上へ
    p = e.replicator
    p.mode = 'GRID'
    p.count_x = 2
    p.count_y = 2
    p.count_z = 1
    p.spacing_x = p.spacing_y = 300.0
    bpy.context.view_layer.update()
    replicator.apply_transforms(e)

    ni = n_instances()
    log("light instance count:", ni, "(expect 4)")
    check("ライト4個がインスタンスとして出る", ni == 4)

    # 複製元のライトはタイプ LIGHT として複製元一覧に入る
    srcs = replicator.gather_sources(e)
    check("ライトが複製元として認識される", len(srcs) == 1 and srcs[0].type == 'LIGHT')

    # レンダーして床が照らされるか
    bpy.context.scene.render.filepath = os.path.join(TMP, "_p17_lit.png")
    bpy.ops.render.render(write_still=True)
    b_lit = brightness(bpy.context.scene.render.filepath)
    log("with cloned lights:", round(b_lit, 3), "(dark=%.3f)" % b_dark)
    check("複製ライトが床を照らす(明るさ増)", b_lit > b_dark + 0.05,
          "lit=%.3f dark=%.3f" % (b_lit, b_dark))

    # 数を増やすと反映(3x3x1=9)
    p.count_x = 3
    p.count_y = 3
    replicator.apply_transforms(e)
    check("数変更でライトも増える(9個)", n_instances() == 9)

    # ===== メッシュ + ライトの混在(分配) =====
    clear()
    setup_render()
    mk_floor()
    cube = mk_cube("cube", 0.6)
    light2 = mk_point_light("L2", 2000.0)
    e2 = replicator.create_replicator(bpy.context, [cube, light2])
    e2.location = (0.0, 0.0, 6.0)
    p2 = e2.replicator
    p2.mode = 'GRID'
    p2.count_x = 4
    p2.count_y = 4
    p2.count_z = 1
    p2.spacing_x = p2.spacing_y = 200.0
    p2.dist_seed = 1
    replicator.apply_transforms(e2)
    total = n_instances()
    log("mesh+light mixed instances:", total, "(expect 16)")
    check("メッシュ+ライト混在で全点インスタンス化", total == 16)
    check("複製元2種(メッシュ+ライト)", len(replicator.gather_sources(e2)) == 2)

    # ===== 回帰: メッシュのみ(従来通り) =====
    clear()
    cube3 = mk_cube("cube3", 0.5)
    e3 = replicator.create_replicator(bpy.context, [cube3])
    e3.replicator.count_x = 3
    e3.replicator.count_y = 3
    e3.replicator.count_z = 3
    replicator.apply_transforms(e3)
    check("回帰: メッシュのみ27個", n_instances() == 27)

    log("=== RESULT:", "ALL PASS ===" if not _fails else ("SOME FAILED: %s ===" % _fails))


main()
