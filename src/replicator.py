# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# D_Replicator — Cinema 4D MoGraph 風クローン (by D_plugins)
# Copyright (C) 2026 D_plugins
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version. This program is distributed WITHOUT ANY WARRANTY. See the GNU GPL
# <https://www.gnu.org/licenses/> for details.
# アーキ: Python(numpy)で全クローンの変換を計算 → 極小 Geometry Nodes(表示専用)へ
#         foreach_set 一括投入。ロジックは全て Python。実 Object は作らない。
# 機能: Grid/Linear/Radial/Circle/Mesh/Spline、間隔XYZ、入れ子、内蔵段階トランスフォーム、
#       複数オブジェクト×ランダム分配(Collection Info + Pick Instance)、
#       モジュレータ・スタック(Random/Step/Time を複数積む)、
#       Field(球/箱/リニア/ノイズ: 0..1 重み。各モジュレータ/段階を個別にゲート)、
#       Mesh モード(頂点/辺/面の中心 + 面上ランダム散布。評価メッシュ追従・揃え軸選択)、
#       Spline モード(カーブ上に弧長等間隔。接線揃え)、
#       複製元にライト可(GN インスタンスとして実際に照らす = EEVEE Next / Cycles)、
#       日英 i18n(ネイティブ翻訳辞書 + パネル上部の言語トグル)。
# 対象: Blender 5.1

bl_info = {
    "name": "D_Replicator",
    "author": "D_plugins",
    "version": (0, 10, 4),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Replicator",
    "description": "Cinema 4D MoGraph 風の非破壊クローン (Python 駆動インスタンシング)",
    "category": "Object",
}

import random as _pyrandom
import bpy
import numpy as np
from mathutils import Vector, geometry as _geo
from bpy.props import (IntProperty, FloatProperty, FloatVectorProperty,
                       EnumProperty, BoolProperty, PointerProperty, StringProperty,
                       CollectionProperty)
from bpy.app.handlers import persistent

DISPLAY_TAG = "is_replicator_display"
FIELD_TAG = "is_replicator_field"   # フィールドのギズモ Empty に付与(複製元と区別)
# フィールド種類ごとのギズモ表示(影響範囲の形が直感で分かるように)
FIELD_EMPTY_DISPLAY = {'SPHERE': 'SPHERE', 'BOX': 'CUBE', 'LINEAR': 'SINGLE_ARROW', 'NOISE': 'PLAIN_AXES'}
GN_BASE = "Replicator_Display_GN"
GN_VERSION = 3   # node group 構造のバージョン。変えると既存 Replicator は自動で作り直される。
# 数(count_x/y/z)の上限: セーフティ ON=100 / OFF=1000(OFF は重い設定で Blender が落ちる場合あり)
COUNT_CAP_SAFE = 100
COUNT_CAP_MAX = 1000
# Field は Python 側で Random を変調するだけ(GN 構造は不変)なので GN_VERSION は据え置き。


# ---------------------------------------------------------------- GN 表示backend
def build_display_gn():
    """表示専用ノードグループ。複数の複製元を Collection Info で取り込み、
    Pick Instance + rep_index で各クローンに割り当てる。"""
    ng = bpy.data.node_groups.new(GN_BASE, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nodes, links = ng.nodes, ng.links
    n_in = nodes.new("NodeGroupInput")
    n_out = nodes.new("NodeGroupOutput")
    col_info = nodes.new("GeometryNodeCollectionInfo")
    col_info.inputs["Separate Children"].default_value = True
    # Reset Children OFF = 複製元オブジェクト自身の変換(スケール/回転)を尊重(C4D の Relative 相当)
    col_info.inputs["Reset Children"].default_value = False
    iop = nodes.new("GeometryNodeInstanceOnPoints")
    iop.inputs["Pick Instance"].default_value = True
    a_rot = nodes.new("GeometryNodeInputNamedAttribute")
    a_rot.data_type = 'FLOAT_VECTOR'
    a_rot.inputs["Name"].default_value = "rep_rot"
    a_scl = nodes.new("GeometryNodeInputNamedAttribute")
    a_scl.data_type = 'FLOAT_VECTOR'
    a_scl.inputs["Name"].default_value = "rep_scale"
    a_idx = nodes.new("GeometryNodeInputNamedAttribute")
    a_idx.data_type = 'INT'
    a_idx.inputs["Name"].default_value = "rep_index"
    links.new(n_in.outputs["Geometry"], iop.inputs["Points"])
    links.new(col_info.outputs[0], iop.inputs["Instance"])
    links.new(a_idx.outputs["Attribute"], iop.inputs["Instance Index"])
    links.new(a_rot.outputs["Attribute"], iop.inputs["Rotation"])
    links.new(a_scl.outputs["Attribute"], iop.inputs["Scale"])
    # Realize 切替: OFF=インスタンスのまま(軽い) / ON=実ジオメトリ化(通常モディファイヤが効く)
    realize = nodes.new("GeometryNodeRealizeInstances")
    switch = nodes.new("GeometryNodeSwitch")
    switch.input_type = 'GEOMETRY'
    links.new(iop.outputs["Instances"], realize.inputs[0])
    links.new(iop.outputs["Instances"], switch.inputs[1])   # False = インスタンス
    links.new(realize.outputs[0], switch.inputs[2])         # True  = ジオメトリ化
    links.new(switch.outputs[0], n_out.inputs["Geometry"])
    ng["rep_version"] = GN_VERSION
    return ng


def _collection_info_node(display):
    mod = display.modifiers.get("Replicator")
    if not mod or not mod.node_group:
        return None
    for nd in mod.node_group.nodes:
        if nd.bl_idname == 'GeometryNodeCollectionInfo':
            return nd
    return None


def set_collection(display, collection):
    nd = _collection_info_node(display)
    if nd is not None:
        nd.inputs["Collection"].default_value = collection


def _switch_node(display):
    mod = display.modifiers.get("Replicator")
    if not mod or not mod.node_group:
        return None
    for nd in mod.node_group.nodes:
        if nd.bl_idname == 'GeometryNodeSwitch':
            return nd
    return None


def set_realize(display, value):
    nd = _switch_node(display)
    if nd is not None:
        nd.inputs[0].default_value = bool(value)


def ensure_gn(display):
    """node group のバージョンが古ければ作り直す = 既存 Replicator を自動移行。"""
    mod = display.modifiers.get("Replicator")
    if not mod:
        return
    if mod.node_group is None or mod.node_group.get("rep_version") != GN_VERSION:
        mod.node_group = build_display_gn()


# ---------------------------------------------------------------- クローン計算
def _axis_up(axis):
    """track 軸に対する up 軸(track と平行にならないよう選ぶ)。"""
    return axis, ('Z' if axis in ('Y', '-Y') else 'Y')


def _vectors_to_euler(vecs, track='Z', up='Y'):
    """各方向ベクトル(法線/接線)に対し、クローンの track 軸をその向きへ揃える
    euler(XYZ, rad)を返す。ロールは to_track_quat(track, up) で解決。"""
    n = len(vecs)
    out = np.zeros((n, 3), dtype=np.float32)
    for i in range(n):
        v = Vector((float(vecs[i, 0]), float(vecs[i, 1]), float(vecs[i, 2])))
        if v.length < 1e-8:
            continue
        e = v.to_track_quat(track, up).to_euler('XYZ')
        out[i, 0], out[i, 1], out[i, 2] = e.x, e.y, e.z
    return out


def _read_mesh_elements(me, source):
    """me から (co (n,3), nor (n,3)) を頂点/辺の中心/面の中心で取り出す。"""
    nv = len(me.vertices)
    if source == 'VERTS':
        n = nv
        co = np.empty(n * 3, dtype=np.float32); me.vertices.foreach_get("co", co)
        nor = np.empty(n * 3, dtype=np.float32); me.vertices.foreach_get("normal", nor)
    elif source == 'EDGES':
        n = len(me.edges)
        if n == 0 or nv == 0:
            return None, None
        ev = np.empty(n * 2, dtype=np.int32); me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(-1, 2)
        vco = np.empty(nv * 3, dtype=np.float32); me.vertices.foreach_get("co", vco)
        vco = vco.reshape(-1, 3)
        vnor = np.empty(nv * 3, dtype=np.float32); me.vertices.foreach_get("normal", vnor)
        vnor = vnor.reshape(-1, 3)
        co = (vco[ev[:, 0]] + vco[ev[:, 1]]) * 0.5
        nor = (vnor[ev[:, 0]] + vnor[ev[:, 1]]) * 0.5
    else:  # FACES
        n = len(me.polygons)
        co = np.empty(n * 3, dtype=np.float32); me.polygons.foreach_get("center", co)
        nor = np.empty(n * 3, dtype=np.float32); me.polygons.foreach_get("normal", nor)
    if n == 0:
        return None, None
    return (np.asarray(co, dtype=np.float32).reshape(-1, 3),
            np.asarray(nor, dtype=np.float32).reshape(-1, 3))


def _surface_scatter(me, count, seed):
    """メッシュ表面に count 個を『面積重み』でランダム散布。(co (count,3), nor (count,3))。
    大きい面ほど多く乗る=自然な散らばり。三角形に分割→面積重みで三角を選び→三角内一様点。
    点の並びはシード依存で安定(前から k 個を取れば散布率での増減で既存点が動かない)。"""
    if count <= 0 or len(me.polygons) == 0:
        return None, None
    try:
        me.calc_loop_triangles()
    except Exception:
        pass
    lt = me.loop_triangles
    nt = len(lt)
    if nt == 0:
        return None, None
    tv = np.empty(nt * 3, dtype=np.int32); lt.foreach_get("vertices", tv)
    tv = tv.reshape(-1, 3)
    tnor = np.empty(nt * 3, dtype=np.float32); lt.foreach_get("normal", tnor)
    tnor = tnor.reshape(-1, 3)
    nv = len(me.vertices)
    vco = np.empty(nv * 3, dtype=np.float32); me.vertices.foreach_get("co", vco)
    vco = vco.reshape(-1, 3)
    a, b, c = vco[tv[:, 0]], vco[tv[:, 1]], vco[tv[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    total = area.sum()
    if total <= 1e-12:
        return None, None
    cum = np.cumsum(area)
    rng = np.random.RandomState(int(seed) & 0x7fffffff)
    # 各点に固定の3値(行=点 index)。count を増やしても前の行は不変
    # = 散布率を上げると既存点は動かず点が増えるだけ(密度アニメ向き)。
    rv = rng.random((count, 3))
    pick = np.clip(np.searchsorted(cum, rv[:, 0] * total), 0, nt - 1)
    su = np.sqrt(rv[:, 1])                                  # 三角内一様(重心座標)
    r2 = rv[:, 2]
    w0 = (1.0 - su)[:, None]
    w1 = (su * (1.0 - r2))[:, None]
    w2 = (su * r2)[:, None]
    co = (w0 * a[pick] + w1 * b[pick] + w2 * c[pick]).astype(np.float32)
    nor = tnor[pick].astype(np.float32)
    return co, nor


def _mesh_points(p, empty):
    """参照メッシュの 頂点/辺の中心/面の中心 を Replicator(empty)ローカル空間の点に。
    法線に揃える ON なら base_rot に法線方向の姿勢を入れる。
    『変形後に追従』ON なら評価メッシュ(modifier/変形適用後)を読む。"""
    z = np.zeros((0, 3), dtype=np.float32)
    ref = p.mesh_object
    if ref is None or ref.type != 'MESH':
        return z, z
    eval_ob = None
    me = None
    if p.mesh_use_evaluated:                 # modifier / 変形を適用した評価メッシュ
        try:
            deps = bpy.context.evaluated_depsgraph_get()
            eval_ob = ref.evaluated_get(deps)
            me = eval_ob.to_mesh()           # 一時メッシュ(finally で必ず解放)
        except Exception:
            eval_ob, me = None, None
    if me is None:                           # 素のメッシュ(既定 / 評価取得に失敗)
        eval_ob = None
        me = ref.data
    if me is None:
        return z, z
    try:
        if p.mesh_source == 'SURFACE':       # 面上ランダム散布(面積重み)
            # 実際の個数 = 数 × 散布率(100%=数, 1000%=10倍)
            n_pts = int(round(max(int(p.count_x), 0) * p.scatter_amount / 100.0))
            co, nor = _surface_scatter(me, n_pts, p.scatter_seed)
        else:
            co, nor = _read_mesh_elements(me, p.mesh_source)
        if co is None or len(co) == 0:
            return z, z
        n = len(co)
        # 参照のローカル → Replicator(empty)ローカルへ(net では参照の世界位置に乗る)
        if empty is not None:
            M = np.array(empty.matrix_world.inverted() @ ref.matrix_world, dtype=np.float32)
        else:
            M = np.array(ref.matrix_world, dtype=np.float32)
        pos = (co @ M[:3, :3].T + M[:3, 3]).astype(np.float32)
        if p.mesh_align:
            nworld = nor @ M[:3, :3].T        # 法線を同じ線形部で回す(均一スケール前提)
            track, up = _axis_up(p.align_axis)
            base_rot = _vectors_to_euler(nworld, track, up)
        else:
            base_rot = np.zeros((n, 3), dtype=np.float32)
        return pos, base_rot.astype(np.float32)
    finally:
        if eval_ob is not None:
            try:
                eval_ob.to_mesh_clear()
            except Exception:
                pass


def _curve_polyline(curve_ob):
    """カーブの各スプラインを (verts (M,3), cyclic) の折れ線に。
    Bezier は resolution_u でテッセレート、POLY/NURBS は制御点を直接使う(NURBS は近似)。"""
    cu = curve_ob.data
    res = max(getattr(cu, "resolution_u", 12), 1)
    out = []
    for sp in cu.splines:
        if sp.type == 'BEZIER' and len(sp.bezier_points) >= 2:
            bp = sp.bezier_points
            m = len(bp)
            segs = m if sp.use_cyclic_u else m - 1
            pts = []
            for i in range(segs):
                a = bp[i]
                b = bp[(i + 1) % m]
                chunk = _geo.interpolate_bezier(a.co, a.handle_right,
                                                b.handle_left, b.co, res + 1)
                pts.extend(tuple(v) for v in chunk[:-1])   # 末尾は次segと重複 → 除く
            if not sp.use_cyclic_u:
                pts.append(tuple(bp[-1].co))               # 開いた線は終点を足す
            if len(pts) >= 2:
                out.append((np.array(pts, dtype=np.float64), sp.use_cyclic_u))
        elif len(sp.points) >= 2:
            pts = np.array([tuple(pt.co)[:3] for pt in sp.points], dtype=np.float64)
            out.append((pts, sp.use_cyclic_u))
    return out


def _resample_polyline(verts, n, cyclic):
    """折れ線 verts を弧長で n 等分し、(pts (n,3), tangents (n,3)) を返す。"""
    verts = np.asarray(verts, dtype=np.float64)
    if cyclic:
        verts = np.vstack([verts, verts[:1]])              # 閉じる
    seg = np.diff(verts, axis=0)
    seglen = np.linalg.norm(seg, axis=1)
    if len(seglen) == 0 or seglen.sum() <= 1e-9:
        p0 = verts[0] if len(verts) else np.zeros(3)
        pts = np.repeat(p0[None, :], n, axis=0)
        tang = np.tile([0.0, 0.0, 1.0], (n, 1))
        return pts.astype(np.float32), tang.astype(np.float32)
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    total = cum[-1]
    targets = np.linspace(0.0, total, n, endpoint=not cyclic)
    idx = np.clip(np.searchsorted(cum, targets, side='right') - 1, 0, len(seglen) - 1)
    t = (targets - cum[idx]) / np.maximum(seglen[idx], 1e-9)
    pts = verts[idx] + seg[idx] * t[:, None]
    tang = seg[idx] / np.maximum(seglen[idx][:, None], 1e-9)
    return pts.astype(np.float32), tang.astype(np.float32)


def _spline_points(p, empty):
    """参照スプライン(カーブ)上に count 個を弧長等間隔で配置。
    接線に揃える ON なら base_rot に接線方向の姿勢を入れる。"""
    z = np.zeros((0, 3), dtype=np.float32)
    ref = p.spline_object
    if ref is None or ref.type != 'CURVE':
        return z, z
    chains = _curve_polyline(ref)
    if not chains:
        return z, z
    verts, cyclic = chains[0]                  # v1: 最初のスプライン
    n = max(p.count_x, 1)
    pts, tang = _resample_polyline(verts, n, cyclic)
    if empty is not None:
        M = np.array(empty.matrix_world.inverted() @ ref.matrix_world, dtype=np.float32)
    else:
        M = np.array(ref.matrix_world, dtype=np.float32)
    pos = (pts @ M[:3, :3].T + M[:3, 3]).astype(np.float32)
    if p.spline_align:
        tworld = tang @ M[:3, :3].T
        track, up = _axis_up(p.align_axis)
        base_rot = _vectors_to_euler(tworld, track, up)
    else:
        base_rot = np.zeros((n, 3), dtype=np.float32)
    return pos, base_rot.astype(np.float32)


def compute_points(p, empty=None):
    """(pos (N,3), base_rot (N,3) rad) を返す。base_rot は円形 Align / メッシュ法線揃え用の基準姿勢。"""
    sx, sy, sz = p.spacing_x * 0.01, p.spacing_y * 0.01, p.spacing_z * 0.01
    if p.mode == 'GRID':
        cx, cy, cz = p.count_x, p.count_y, p.count_z
        xs = (np.arange(cx) - (cx - 1) / 2.0) * sx
        ys = (np.arange(cy) - (cy - 1) / 2.0) * sy
        zs = (np.arange(cz) - (cz - 1) / 2.0) * sz
        gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
        pos = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
        base_rot = np.zeros_like(pos)
    elif p.mode == 'LINEAR':
        n = max(p.count_x, 1)
        i = np.arange(n)[:, None]
        pos = i * np.array([sx, sy, sz])
        base_rot = np.zeros((n, 3))
    elif p.mode == 'RADIAL':   # 放射(従来のシンプルな円周。そのまま)
        n = max(p.count_x, 1)
        r = max(sx, 1e-6)      # 間隔X を半径に流用(従来通り)
        a = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
        pos = np.stack([np.cos(a) * r, np.sin(a) * r, np.zeros(n)], axis=1)
        base_rot = np.zeros((n, 3))
    elif p.mode == 'MESH':   # 任意メッシュの頂点/辺/面の中心(C4D オブジェクトモード相当)
        return _mesh_points(p, empty)
    elif p.mode == 'SPLINE':  # スプライン(カーブ)上に弧長等間隔配置
        return _spline_points(p, empty)
    else:  # CIRCLE(円形: 半径/平面/角度/Align)
        n = max(p.count_x, 1)
        r = max(p.radius * 0.01, 0.0)
        arc = np.radians(p.radial_arc)
        endpoint = p.radial_arc < 359.999      # 全周は終点を重複させない
        a = np.linspace(0.0, arc, n, endpoint=endpoint)
        u, v = np.cos(a) * r, np.sin(a) * r
        pos = np.zeros((n, 3))
        base_rot = np.zeros((n, 3))
        if p.radial_plane == 'XY':
            pos[:, 0], pos[:, 1] = u, v
            if p.radial_align:
                base_rot[:, 2] = a
        elif p.radial_plane == 'XZ':
            pos[:, 0], pos[:, 2] = u, v
            if p.radial_align:
                base_rot[:, 1] = -a
        else:  # YZ
            pos[:, 1], pos[:, 2] = u, v
            if p.radial_align:
                base_rot[:, 0] = a
    return pos.astype(np.float32), base_rot.astype(np.float32)


def _field_local(empty, fo, pos):
    """クローン位置(empty ローカル, (N,3))をフィールドのローカル空間へ変換。
    フィールドのスケール/回転がそのまま影響範囲の形・向き・大きさになる。"""
    T = np.array(fo.matrix_world.inverted() @ empty.matrix_world, dtype=np.float32)
    return pos @ T[:3, :3].T + T[:3, 3]


def _shape(g, falloff):
    """g(1=芯 / 0=境界の外)を falloff で整形 → 0..1。
    falloff=1: 中心から滑らかな勾配 / falloff→0: 縁が立ったハードエッジ。"""
    f = min(max(falloff, 1e-4), 1.0)
    t = np.clip(g / f, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)            # smoothstep


def _hash_lattice(px, py, pz):
    s = np.sin(px * 12.9898 + py * 78.233 + pz * 37.719) * 43758.5453
    return s - np.floor(s)                    # fract → [0,1)


def _value_noise(coords):
    """3D value noise(trilinear + smoothstep)→ [0,1)。numpy のみ(scipy 不要)。"""
    c = coords.astype(np.float64)
    fl = np.floor(c)
    u = (c - fl) ** 2 * (3.0 - 2.0 * (c - fl))
    fx, fy, fz = fl[:, 0], fl[:, 1], fl[:, 2]
    ux, uy, uz = u[:, 0], u[:, 1], u[:, 2]

    def H(dx, dy, dz):
        return _hash_lattice(fx + dx, fy + dy, fz + dz)

    x00 = H(0, 0, 0) * (1 - ux) + H(1, 0, 0) * ux
    x10 = H(0, 1, 0) * (1 - ux) + H(1, 1, 0) * ux
    x01 = H(0, 0, 1) * (1 - ux) + H(1, 0, 1) * ux
    x11 = H(0, 1, 1) * (1 - ux) + H(1, 1, 1) * ux
    y0 = x00 * (1 - uy) + x10 * uy
    y1 = x01 * (1 - uy) + x11 * uy
    return y0 * (1 - uz) + y1 * uz


def compute_field_weight(p, empty, pos):
    """各クローン位置(empty ローカル, (N,3))に対する 0..1 の重み。
    フィールド無効なら全 1。種類: 球 / 箱 / リニア / ノイズ。"""
    n = len(pos)
    if n == 0 or not p.field_enable or p.field_object is None or empty is None:
        return np.ones(max(n, 0), dtype=np.float32)
    fo = p.field_object
    local = _field_local(empty, fo, pos)         # (n,3) フィールドローカル空間
    R = max(p.field_radius * 0.01, 1e-6)
    ft = p.field_type
    if ft == 'SPHERE':
        d = np.linalg.norm(local, axis=1)
        w = _shape(np.clip((R - d) / R, 0.0, 1.0), p.field_falloff)
    elif ft == 'BOX':
        g = (R - np.max(np.abs(local), axis=1)) / R   # 一番外れた軸で内外が決まる
        w = _shape(np.clip(g, 0.0, 1.0), p.field_falloff)
    elif ft == 'LINEAR':
        g = np.clip(local[:, 2] / R, 0.0, 1.0)        # 矢印(ローカル +Z)の先側が強い
        w = _shape(g, p.field_falloff)
    else:  # NOISE
        w = _shape(_value_noise(local / R), p.field_falloff)
    w = np.asarray(w, dtype=np.float32)
    if p.field_invert:
        w = 1.0 - w
    return w.astype(np.float32)


def _time_seconds():
    """現在フレームを秒に(Time モジュレータ用)。frame_start を 0 秒の基準にする。"""
    try:
        sc = bpy.context.scene
        fps = sc.render.fps / max(sc.render.fps_base, 1e-6)
        return (sc.frame_current - sc.frame_start) / max(fps, 1e-6)
    except Exception:
        return 0.0


def _apply_modulator(m, pos, rot, scale, ramp_norm, ramp_acc, wm, t_sec, n):
    """1つのモジュレータの寄与を pos/rot/scale に加える。wm=(n,) 0..1 のフィールド重み。"""
    s = m.strength
    mp = np.array(m.pos[:], dtype=np.float32) * 0.01 * s     # 位置 (m)
    mr = np.radians(np.array(m.rot[:], dtype=np.float32)) * s  # 回転 (rad)
    msc = m.scale * s                                        # スケール量
    wc = wm[:, None]
    if m.mtype == 'RANDOM':
        rng = np.random.RandomState(m.seed)
        rp = rng.random((n, 3)).astype(np.float32) * 2.0 - 1.0
        rr = rng.random((n, 3)).astype(np.float32) * 2.0 - 1.0
        rs = rng.random(n).astype(np.float32) * 2.0 - 1.0
        pos = pos + rp * mp * wc
        rot = rot + rr * mr * wc
        scale = scale * (1.0 + rs * msc * wm)[:, None]
    elif m.mtype == 'STEP':
        sr = (ramp_norm if m.normalized else ramp_acc)        # (n,1)
        pos = pos + sr * mp * wc
        rot = rot + sr * mr * wc
        scale = scale * (1.0 + sr * msc * wc)
    else:  # TIME(時間で累積。キーフレーム不要)
        tt = t_sec * m.speed
        pos = pos + (mp * tt) * wc
        rot = rot + (mr * tt) * wc
        scale = scale * (1.0 + (msc * tt) * wm)[:, None]
    return pos, rot, scale


def compute_clone_data(p, empty=None):
    """位置(N,3)・回転rad(N,3)・スケール(N,3)。内蔵段階 + モジュレータ・スタックを順に合成。
    共有フィールドの重みは『フィールドで絞る』ON の段階/モジュレータにだけ掛かる。"""
    pos, base_rot = compute_points(p, empty)
    n = len(pos)
    # 段階/Step 用の ramp: 正規化 = 端→端 0..1 / 累積 = 0,1,2,..(クローン数で暴れる側)
    ramp_acc = np.arange(n, dtype=np.float32)[:, None]
    ramp_norm = (ramp_acc / float(n - 1)) if n > 1 else ramp_acc
    rot = base_rot.copy()   # 円形 Align の基準姿勢から開始
    scale = np.ones((n, 3), dtype=np.float32) * np.array(p.base_scale[:], dtype=np.float32)
    if n == 0:
        return pos.astype(np.float32), rot.astype(np.float32), scale.astype(np.float32)

    # 共有フィールド重みはベース位置で1回だけ評価(対象同士で循環しない)
    ones = np.ones(n, dtype=np.float32)
    w_field = compute_field_weight(p, empty, pos)             # (n,) 0..1。無効なら全 1

    # 内蔵 段階トランスフォーム(step_use_field=ON ならフィールドで絞る)
    step_ramp = ramp_norm if p.step_normalized else ramp_acc
    ws = (w_field if p.step_use_field else ones)[:, None]
    pos = pos + step_ramp * (np.array(p.step_pos[:], dtype=np.float32) * 0.01) * ws
    rot = rot + step_ramp * np.radians(np.array(p.step_rot[:], dtype=np.float32)) * ws
    scale = scale * (1.0 + step_ramp * p.step_scale * ws)

    # モジュレータ・スタック(上から順に適用)
    t_sec = _time_seconds()
    for m in p.modulators:
        if not m.enable:
            continue
        wm = w_field if m.use_field else ones
        pos, rot, scale = _apply_modulator(m, pos, rot, scale, ramp_norm, ramp_acc, wm, t_sec, n)

    scale = np.maximum(scale, 1e-3)   # 負/ゼロスケールでの暴れを防止
    return pos.astype(np.float32), rot.astype(np.float32), scale.astype(np.float32)


def compute_index(p, n, n_sources):
    """各クローンがどの複製元を使うか(seed で決まるランダム分配)。"""
    if n_sources <= 1 or n == 0:
        return np.zeros(n, dtype=np.int32)
    rng = np.random.RandomState(p.dist_seed)
    return rng.randint(0, n_sources, size=n).astype(np.int32)


def write_display(display, pos, rot, scale, idx):
    me = display.data
    n = len(pos)
    if len(me.vertices) != n:
        me.clear_geometry()
        if n:
            me.vertices.add(n)
    if "rep_rot" not in me.attributes:
        me.attributes.new("rep_rot", 'FLOAT_VECTOR', 'POINT')
    if "rep_scale" not in me.attributes:
        me.attributes.new("rep_scale", 'FLOAT_VECTOR', 'POINT')
    if "rep_index" not in me.attributes:
        me.attributes.new("rep_index", 'INT', 'POINT')
    if n:
        me.vertices.foreach_set("co", pos.reshape(-1))
        me.attributes["rep_rot"].data.foreach_set("vector", rot.reshape(-1))
        me.attributes["rep_scale"].data.foreach_set("vector", scale.reshape(-1))
        me.attributes["rep_index"].data.foreach_set("value", idx)
    me.update()


# ---------------------------------------------------------------- 親子 / 複製元
def get_display(empty):
    for c in empty.children:
        if c.get(DISPLAY_TAG):
            return c
    return None


def get_field(empty):
    """この Replicator のフィールドギズモ Empty を返す(無ければ None)。"""
    p = getattr(empty, "replicator", None)
    fo = p.field_object if p else None
    if fo is not None and fo.name in bpy.data.objects:
        return fo
    return None


def ensure_field(empty):
    """フィールドギズモ(SPHERE 表示の Empty)を作成 or 取得し、Replicator の子にする。
    新規時はグリッド中心(empty ローカル原点)に置く = 掴んで動かす起点。"""
    p = empty.replicator
    fo = get_field(empty)
    if fo is None:
        fo = bpy.data.objects.new(empty.name + "_Field", None)
        fo[FIELD_TAG] = True
        fo.empty_display_type = FIELD_EMPTY_DISPLAY.get(p.field_type, 'SPHERE')
        fo.empty_display_size = max(p.field_radius * 0.01, 0.001)
        coll = empty.users_collection[0] if empty.users_collection else bpy.context.scene.collection
        coll.objects.link(fo)
        fo.parent = empty               # matrix_parent_inverse は既定の単位行列のまま
        fo.location = (0.0, 0.0, 0.0)   # = empty 原点 = グリッド中心
        p.field_object = fo
    return fo


def is_replicator_empty(ob):
    p = getattr(ob, "replicator", None)
    return bool(ob and ob.type == 'EMPTY' and p and p.is_replicator)


def _set_collection_in_scene(col, visible):
    """src_col をシーン(ビューレイヤー)に出すか。出す=複製元が編集用に見える。"""
    scene_col = bpy.context.scene.collection
    linked = any(ch is col for ch in scene_col.children)
    if visible and not linked:
        try:
            scene_col.children.link(col)
        except Exception:
            pass
    elif not visible and linked:
        try:
            scene_col.children.unlink(col)
        except Exception:
            pass


def gather_sources(empty):
    """複製元の一覧。子がメッシュ/ライトならそれ、子が Replicator ならその表示メッシュ(入れ子)。
    ライトは GN インスタンスとして実際に照らす(EEVEE Next / Cycles で確認済)。"""
    out = []
    for c in empty.children:
        if c.get(DISPLAY_TAG) or c.get(FIELD_TAG):
            continue
        if is_replicator_empty(c):
            d = get_display(c)
            if d:
                out.append(d)
        elif c.type in ('MESH', 'LIGHT'):
            out.append(c)
    return out


def sync_source_collection(empty, sources):
    col = empty.replicator.src_collection
    if col is None:
        return
    want = set(sources)
    # src_col から不要なものを外す
    for o in list(col.objects):
        if o not in want:
            try:
                col.objects.unlink(o)
            except Exception:
                pass
    for o in want:
        # Collection Info 用に src_col へ
        if o.name not in col.objects:
            try:
                col.objects.link(o)
            except Exception:
                pass
        # 旧方式の隠しフラグをクリア(可視はコレクション所属で制御。既存Replicatorの自動移行)
        o.hide_render = False
        try:
            o.hide_set(False)
        except Exception:
            pass
        # 複製元は src_col のみに所属させる(単体での表示/レンダーを防ぐ)
        for c in list(o.users_collection):
            if c is not col:
                try:
                    c.objects.unlink(o)
                except Exception:
                    pass
    # 編集表示: ON ならメッシュ複製元をシーンにも出す(入れ子の内側表示は除く)
    if empty.replicator.show_sources:
        scene_col = bpy.context.scene.collection
        for o in want:
            if not o.get(DISPLAY_TAG) and o.name not in scene_col.objects:
                try:
                    scene_col.objects.link(o)
                except Exception:
                    pass


def apply_transforms(empty):
    """軽量更新: クローンの変換のみ書き込む(コレクション/可視/ノードは触らない)。
    frame_change ハンドラから安全に呼べる = レンダー/再生中にシーン構造を変更しない。"""
    if not is_replicator_empty(empty):
        return
    p = empty.replicator
    display = get_display(empty)
    if not display:
        return
    n_src = len(p.src_collection.objects) if p.src_collection else 0
    pos, rot, scale = compute_clone_data(p, empty)
    idx = compute_index(p, len(pos), n_src)
    write_display(display, pos, rot, scale, idx)


def _migrate_to_stack(p):
    """旧: 単体 Random + field_affect → 新: モジュレータ・スタック + step_use_field。一度だけ。"""
    if p.get("_stack_migrated"):
        return
    p["_stack_migrated"] = True   # 先にフラグ(移行中の prop 更新で再入しても二重移行しない)
    # 旧 field_affect の段階分を step_use_field へ
    if getattr(p, "field_affect", 'RANDOM') in ('STEP', 'BOTH'):
        p.step_use_field = True
    # 旧の単体 Random を Random モジュレータへ移す
    if p.random_enable:
        m = p.modulators.add()
        m.mtype = 'RANDOM'
        m.name = "Random"
        m.pos = p.random_pos
        m.rot = p.random_rot
        m.scale = p.random_scale
        m.seed = p.random_seed
        m.use_field = getattr(p, "field_affect", 'RANDOM') in ('RANDOM', 'BOTH')
        p.random_enable = False
        p.modulator_index = len(p.modulators) - 1


def _migrate_all():
    for ob in bpy.data.objects:
        if is_replicator_empty(ob):
            try:
                _migrate_to_stack(ob.replicator)
                update_replicator(ob)
            except Exception:
                pass


def update_replicator(empty):
    """フル更新(生成 / 複製元の追加削除 / プロパティ操作時)。構造も同期する。"""
    if not is_replicator_empty(empty):
        return
    p = empty.replicator
    _migrate_to_stack(p)
    display = get_display(empty)
    if not display:
        return
    ensure_gn(display)
    sources = gather_sources(empty)
    sync_source_collection(empty, sources)
    set_collection(display, p.src_collection)
    set_realize(display, p.realize_output)
    apply_transforms(empty)


def _upd(self, context):
    update_replicator(self.id_data)


def _upd_count(self, context):
    """セーフティに応じて数(count_x/y/z)を 100 / 1000 にクランプしてから更新。
    クランプは self[...] への直接書き込み(=update を再発火しない)で行い再帰を防ぐ。"""
    cap = COUNT_CAP_SAFE if self.count_safety else COUNT_CAP_MAX
    for attr in ("count_x", "count_y", "count_z"):
        if getattr(self, attr) > cap:
            self[attr] = cap
    update_replicator(self.id_data)


def _upd_field(self, context):
    """フィールド半径の変更時はギズモ Empty の表示サイズも追従(影響範囲を見えるように)。"""
    e = self.id_data
    fo = get_field(e)
    if fo is not None:
        fo.empty_display_size = max(self.field_radius * 0.01, 0.001)
    update_replicator(e)


def _upd_field_type(self, context):
    """種類変更でギズモの表示形状を切替(球/箱/矢印/軸)。"""
    e = self.id_data
    fo = get_field(e)
    if fo is not None:
        fo.empty_display_type = FIELD_EMPTY_DISPLAY.get(self.field_type, 'SPHERE')
    update_replicator(e)


def _poll_mesh_object(self, obj):
    """メッシュモードの参照に選べるのはメッシュのみ(表示メッシュは除外して循環を防ぐ)。"""
    return obj is not None and obj.type == 'MESH' and not obj.get(DISPLAY_TAG)


def _poll_curve_object(self, obj):
    """スプラインモードの参照に選べるのはカーブのみ。"""
    return obj is not None and obj.type == 'CURVE'


# ---------------------------------------------------------------- 翻訳(アドオン内・日英)
# 方針: Blender 全体の言語は変えない。言語は WindowManager(d_replicator_lang)に持ち、
# 描画時に t() で翻訳する(EN=辞書 / JA=原文)。辞書 _TR_EN は下部に定義(実行時に参照)。
def t(s):
    """アドオン内の UI 言語へ翻訳。EN なら辞書、無ければ原文(=日本語)を返す。"""
    try:
        if bpy.context.window_manager.d_replicator_lang == 'EN':
            return _TR_EN.get(s, s)
    except Exception:
        pass
    return s


# 翻訳が要る enum は items をコールバック化して言語連動。表示名/説明のみ訳す(ID は不変)。
_MODE_ITEMS_BASE = [
    ('GRID', "グリッド", "立方格子状"),
    ('LINEAR', "リニア", "原点から1ステップずつ"),
    ('RADIAL', "放射", "円周状(シンプル・従来)"),
    ('CIRCLE', "円形", "半径/平面/角度/Align 対応の円配置"),
    ('MESH', "メッシュ", "任意メッシュの頂点/辺/面の中心に配置(C4D オブジェクトモード相当)"),
    ('SPLINE', "スプライン", "カーブ上に弧長等間隔で配置(C4D スプラインモード相当)"),
]
_MESH_SRC_ITEMS_BASE = [
    ('VERTS', "頂点", "各頂点に配置"),
    ('EDGES', "辺の中心", "各辺の中点に配置"),
    ('FACES', "面の中心", "各面の中心に配置"),
    ('SURFACE', "面上ランダム", "面の上にランダム散布(面積重み)"),
]
_FIELD_TYPE_ITEMS_BASE = [
    ('SPHERE', "球", "中心からの距離で減衰"),
    ('BOX', "箱", "直方体の内側で 1、外で 0"),
    ('LINEAR', "リニア", "矢印(ローカル+Z)方向に沿って減衰"),
    ('NOISE', "ノイズ", "3D ノイズで濃淡(位置/スケールはギズモ基準)"),
]
_ENUM_STORE = {}   # コールバック enum の文字列寿命を保つ(GC によるクラッシュ防止)


def _make_items(name, base):
    out = [(idf, t(nm), t(ds)) for (idf, nm, ds) in base]
    _ENUM_STORE[name] = out
    return out


def _mode_items(self, context):
    return _make_items('mode', _MODE_ITEMS_BASE)


def _mesh_src_items(self, context):
    return _make_items('mesh_source', _MESH_SRC_ITEMS_BASE)


def _field_type_items(self, context):
    return _make_items('field_type', _FIELD_TYPE_ITEMS_BASE)


def _P(layout, data, prop, **kw):
    """prop を翻訳ラベルで描画。text 未指定なら RNA 表示名を訳す。text='' はそのまま(アイコンのみ)。"""
    if "text" in kw:
        if kw["text"]:
            kw["text"] = t(kw["text"])
    else:
        try:
            kw["text"] = t(data.bl_rna.properties[prop].name)
        except Exception:
            pass
    layout.prop(data, prop, **kw)


def _L(layout, s, **kw):
    """翻訳ラベル。"""
    layout.label(text=t(s), **kw)


def _O(layout, idname, s, **kw):
    """翻訳ラベル付きオペレータボタン。"""
    return layout.operator(idname, text=t(s), **kw)


# ---------------------------------------------------------------- データ
class ReplicatorModulator(bpy.types.PropertyGroup):
    """スタックに積む変調器1つ。種類で挙動が変わる(Random/Step/Time)。"""
    name: StringProperty(default="Modulator")
    enable: BoolProperty(name="有効", default=True, update=_upd)
    mtype: EnumProperty(name="種類",
                        items=[('RANDOM', "Random", "クローンごとにランダム"),
                               ('STEP', "Step", "クローン列に沿った勾配(0→1)"),
                               ('TIME', "Time", "時間で累積(キーフレーム不要)")],
                        default='RANDOM', update=_upd)
    pos: FloatVectorProperty(name="位置 (cm)", size=3, subtype='XYZ',
                             default=(0.0, 0.0, 0.0), update=_upd)
    rot: FloatVectorProperty(name="回転 (度)", size=3, subtype='XYZ',
                             default=(0.0, 0.0, 0.0), update=_upd)
    scale: FloatProperty(name="スケール", default=0.0, update=_upd)
    strength: FloatProperty(name="強度", default=1.0, min=0.0, soft_max=1.0, update=_upd)
    seed: IntProperty(name="シード", default=0, update=_upd)            # RANDOM 用
    normalized: BoolProperty(name="正規化(端→端 0→1)", default=True, update=_upd)  # STEP 用
    speed: FloatProperty(name="速度", default=1.0, update=_upd)         # TIME 用
    use_field: BoolProperty(name="フィールドで絞る", default=False, update=_upd)


class ReplicatorProps(bpy.types.PropertyGroup):
    is_replicator: BoolProperty(default=False)
    src_collection: PointerProperty(type=bpy.types.Collection)
    show_sources: BoolProperty(name="複製元を表示(編集用)", default=False, update=_upd)
    mode: EnumProperty(name="モード", items=_mode_items, update=_upd)   # 既定=先頭(GRID)
    count_safety: BoolProperty(
        name="セーフティ(数を最大100に制限)", default=True, update=_upd_count,
        description="OFF で最大1000まで許容。クローン数が多いと Blender が落ちる場合あり")
    count_x: IntProperty(name="数 X", default=3, min=1, soft_max=COUNT_CAP_MAX,
                         max=COUNT_CAP_MAX, update=_upd_count)
    count_y: IntProperty(name="数 Y", default=3, min=1, soft_max=COUNT_CAP_MAX,
                         max=COUNT_CAP_MAX, update=_upd_count)
    count_z: IntProperty(name="数 Z", default=3, min=1, soft_max=COUNT_CAP_MAX,
                         max=COUNT_CAP_MAX, update=_upd_count)
    spacing_x: FloatProperty(name="X", default=200.0, update=_upd)
    spacing_y: FloatProperty(name="Y", default=200.0, update=_upd)
    spacing_z: FloatProperty(name="Z", default=200.0, update=_upd)
    # 円形(放射)モード
    radius: FloatProperty(name="半径 (cm)", default=200.0, min=0.0, update=_upd)
    radial_plane: EnumProperty(name="平面",
                               items=[('XY', "XY", ""), ('XZ', "XZ", ""), ('YZ', "YZ", "")],
                               default='XY', update=_upd)
    radial_arc: FloatProperty(name="角度 (度)", default=360.0, min=0.0, soft_max=360.0, update=_upd)
    radial_align: BoolProperty(name="軸を外向きに揃える", default=True, update=_upd)
    # メッシュモード(任意メッシュの頂点/辺/面の中心に配置 = C4D オブジェクトモード相当)
    mesh_object: PointerProperty(name="参照メッシュ", type=bpy.types.Object,
                                 poll=_poll_mesh_object, update=_upd)
    mesh_source: EnumProperty(name="配置先", items=_mesh_src_items, update=_upd)  # 既定=先頭(VERTS)
    # 面上ランダム散布(SURFACE)用
    scatter_amount: FloatProperty(name="散布率", default=100.0, min=0.0, max=1000.0,
                                  soft_max=1000.0, subtype='PERCENTAGE',
                                  description="100%=「数」個が基準。0〜1000%(最大10倍)。"
                                              "前から増えるので率を変えても既存点は動かない",
                                  update=_upd)
    scatter_seed: IntProperty(name="シード", default=0, update=_upd)
    mesh_align: BoolProperty(name="法線に揃える", default=True,
                             description="クローンの揃え軸を頂点/面の法線方向へ向ける", update=_upd)
    mesh_use_evaluated: BoolProperty(name="変形後に追従(評価メッシュ)", default=False,
                                     description="参照のモディファイヤ/変形を適用した後の形に配置(重い)",
                                     update=_upd)
    # 揃え軸(メッシュ法線 / スプライン接線で共有): どのローカル軸を向ける方向に合わせるか
    align_axis: EnumProperty(name="揃える軸",
                             items=[('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", ""),
                                    ('-X', "-X", ""), ('-Y', "-Y", ""), ('-Z', "-Z", "")],
                             default='Z', update=_upd)
    # スプラインモード(カーブ上に弧長等間隔配置 = C4D スプラインモード相当)
    spline_object: PointerProperty(name="参照スプライン", type=bpy.types.Object,
                                   poll=_poll_curve_object, update=_upd)
    spline_align: BoolProperty(name="接線に揃える", default=True,
                               description="クローンの揃え軸をカーブの進行方向(接線)へ向ける", update=_upd)
    # 複製元の基準サイズ(Replicator から直接いじれる大きさ)
    base_scale: FloatVectorProperty(name="基準スケール", size=3, subtype='XYZ',
                                    default=(1.0, 1.0, 1.0), update=_upd)
    realize_output: BoolProperty(name="出力をジオメトリ化(Realize)", default=False, update=_upd)
    # 内蔵 段階トランスフォーム
    step_normalized: BoolProperty(name="正規化(端→端 0→1)", default=True, update=_upd)
    step_pos: FloatVectorProperty(name="位置/ステップ (cm)", size=3, subtype='XYZ',
                                  default=(0.0, 0.0, 0.0), update=_upd)
    step_rot: FloatVectorProperty(name="回転/ステップ (度)", size=3, subtype='XYZ',
                                  default=(0.0, 0.0, 0.0), update=_upd)
    step_scale: FloatProperty(name="スケール/ステップ", default=0.0, update=_upd)
    step_use_field: BoolProperty(name="フィールドで絞る", default=False, update=_upd)
    # モジュレータ・スタック(Random / Step / Time を複数積む)
    modulators: CollectionProperty(type=ReplicatorModulator)
    modulator_index: IntProperty(default=0)
    # 複数オブジェクト分配
    dist_seed: IntProperty(name="分配シード", default=0, update=_upd)
    # Random(単体・旧/移行用。新規 UI には出さずスタックへ自動移行)
    random_enable: BoolProperty(name="ランダム", default=False, update=_upd)
    random_seed: IntProperty(name="シード", default=0, update=_upd)
    random_pos: FloatVectorProperty(name="位置 (cm)", size=3, subtype='XYZ',
                                    default=(0.0, 0.0, 0.0), update=_upd)
    random_rot: FloatVectorProperty(name="回転 (度)", size=3, subtype='XYZ',
                                    default=(0.0, 0.0, 0.0), update=_upd)
    random_scale: FloatProperty(name="スケール", default=0.0, min=0.0, soft_max=1.0,
                                update=_upd)
    # Field(球/箱/リニア/ノイズ: Random・段階トランスフォームの per-clone 強度を 0..1 重みで変調)
    field_enable: BoolProperty(name="フィールド", default=False, update=_upd)
    field_object: PointerProperty(type=bpy.types.Object)
    field_affect: EnumProperty(name="効かせる対象",
                               items=[('RANDOM', "Random", "ランダムにのみ効く"),
                                      ('STEP', "段階", "段階トランスフォームにのみ効く"),
                                      ('BOTH', "両方", "Random と段階トランスフォーム両方に効く")],
                               default='RANDOM', update=_upd)
    field_type: EnumProperty(name="種類", items=_field_type_items,
                             update=_upd_field_type)   # 既定=先頭(SPHERE)
    field_radius: FloatProperty(name="半径/長さ/スケール (cm)", default=300.0, min=0.0,
                                description="球=半径 / 箱=半幅 / リニア=長さ / ノイズ=粒の大きさ",
                                update=_upd_field)
    field_falloff: FloatProperty(name="減衰幅", default=1.0, min=0.0, max=1.0,
                                 description="0=芯だけで急に切れる / 1=滑らかに減衰",
                                 update=_upd)
    field_invert: BoolProperty(name="反転", default=False, update=_upd)


# ---------------------------------------------------------------- 生成 / オペレータ
def create_replicator(context, sources=None):
    coll = context.collection or context.scene.collection
    empty = bpy.data.objects.new("Replicator", None)
    empty.empty_display_type = 'PLAIN_AXES'
    coll.objects.link(empty)
    empty.replicator.is_replicator = True

    src_col = bpy.data.collections.new(empty.name + "_Sources")
    # src_col はシーン(ビューレイヤー)にリンクしない = 複製元は単体表示/レンダーされない。
    # Collection Info が依存として評価するのでインスタンスは出る。
    empty.replicator.src_collection = src_col

    me = bpy.data.meshes.new("Replicator_Display")
    disp = bpy.data.objects.new("Replicator_Display", me)
    disp[DISPLAY_TAG] = True
    coll.objects.link(disp)
    disp.parent = empty
    mod = disp.modifiers.new("Replicator", "NODES")
    mod.node_group = build_display_gn()

    for s in (sources or []):
        s.parent = empty
        s.matrix_parent_inverse = empty.matrix_world.inverted()

    update_replicator(empty)
    return empty


class OBJECT_OT_add_replicator(bpy.types.Operator):
    bl_idname = "object.add_replicator"
    bl_label = "Replicator を追加"
    bl_description = "選択中のメッシュ/ライト/Replicator を複製元にして Replicator を作成"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        srcs = [o for o in context.selected_objects
                if o.type in ('MESH', 'LIGHT') or is_replicator_empty(o)]
        empty = create_replicator(context, srcs)
        for o in context.selected_objects:
            o.select_set(False)
        empty.select_set(True)
        context.view_layer.objects.active = empty
        return {'FINISHED'}


class OBJECT_OT_replicator_refresh(bpy.types.Operator):
    bl_idname = "object.replicator_refresh"
    bl_label = "更新"
    bl_options = {'REGISTER'}

    def execute(self, context):
        update_replicator(context.active_object)
        return {'FINISHED'}


class OBJECT_OT_replicator_dice(bpy.types.Operator):
    bl_idname = "object.replicator_dice"
    bl_label = "分配シード振り直し"
    bl_description = "複製元の分配シードを引き直して別の組み合わせを探す"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = context.active_object
        if is_replicator_empty(ob):
            ob.replicator.dist_seed = _pyrandom.randint(0, 999999)
        return {'FINISHED'}


class OBJECT_OT_replicator_scatter_dice(bpy.types.Operator):
    bl_idname = "object.replicator_scatter_dice"
    bl_label = "散布シード振り直し"
    bl_description = "面上ランダム散布のシードを引き直して別パターンを探す"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = context.active_object
        if is_replicator_empty(ob):
            ob.replicator.scatter_seed = _pyrandom.randint(0, 999999)
        return {'FINISHED'}


class OBJECT_OT_modulator_add(bpy.types.Operator):
    bl_idname = "object.replicator_modulator_add"
    bl_label = "モジュレータ追加"
    bl_description = "Random / Step / Time のモジュレータをスタックに追加"
    bl_options = {'REGISTER', 'UNDO'}
    mtype: StringProperty(default='RANDOM')

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        p = e.replicator
        m = p.modulators.add()
        m.mtype = self.mtype
        # 種類別の「置いた瞬間それらしい」デフォルト(North Star)
        if self.mtype == 'RANDOM':
            m.name = "Random"
            m.pos = (50.0, 50.0, 50.0)
            m.seed = _pyrandom.randint(0, 999999)
        elif self.mtype == 'STEP':
            m.name = "Step"
            m.rot = (0.0, 0.0, 90.0)
        else:  # TIME
            m.name = "Time"
            m.rot = (0.0, 0.0, 90.0)
            m.speed = 1.0
        p.modulator_index = len(p.modulators) - 1
        update_replicator(e)
        return {'FINISHED'}


class OBJECT_OT_modulator_remove(bpy.types.Operator):
    bl_idname = "object.replicator_modulator_remove"
    bl_label = "モジュレータ削除"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        p = e.replicator
        i = p.modulator_index
        if 0 <= i < len(p.modulators):
            p.modulators.remove(i)
            p.modulator_index = max(0, min(i, len(p.modulators) - 1))
            update_replicator(e)
        return {'FINISHED'}


class OBJECT_OT_modulator_move(bpy.types.Operator):
    bl_idname = "object.replicator_modulator_move"
    bl_label = "モジュレータ並べ替え"
    bl_options = {'REGISTER', 'UNDO'}
    direction: StringProperty(default='UP')

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        p = e.replicator
        i = p.modulator_index
        j = i - 1 if self.direction == 'UP' else i + 1
        if 0 <= i < len(p.modulators) and 0 <= j < len(p.modulators):
            p.modulators.move(i, j)
            p.modulator_index = j
            update_replicator(e)
        return {'FINISHED'}


class OBJECT_OT_modulator_dice(bpy.types.Operator):
    bl_idname = "object.replicator_modulator_dice"
    bl_label = "シード振り直し"
    bl_description = "この Random モジュレータのシードを引き直す"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        e = context.active_object
        if is_replicator_empty(e):
            p = e.replicator
            if 0 <= p.modulator_index < len(p.modulators):
                p.modulators[p.modulator_index].seed = _pyrandom.randint(0, 999999)
        return {'FINISHED'}


class OBJECT_OT_replicator_keyframe(bpy.types.Operator):
    bl_idname = "object.replicator_keyframe"
    bl_label = "キーフレーム"
    bl_description = "現在フレームにこのパラメータのキーを打つ/消す(再生・スクラブでアニメ)"
    bl_options = {'REGISTER', 'UNDO'}
    data_path: StringProperty()
    obj_name: StringProperty(default="")   # キーを持たせるオブジェクト名
    remove: BoolProperty(default=False)

    def execute(self, context):
        ob = bpy.data.objects.get(self.obj_name) if self.obj_name else context.active_object
        if ob is None:
            return {'CANCELLED'}
        frame = context.scene.frame_current
        try:
            if self.remove:
                ob.keyframe_delete(self.data_path, index=-1, frame=frame)
            else:
                ob.keyframe_insert(self.data_path, index=-1, frame=frame)
        except Exception as ex:
            self.report({'WARNING'}, "キー操作に失敗: %s" % ex)
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class OBJECT_OT_replicator_add_source(bpy.types.Operator):
    bl_idname = "object.replicator_add_source"
    bl_label = "選択を複製元に追加"
    bl_description = "選択中のメッシュ/ライト/Replicator をこの Replicator の複製元として追加"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        for o in list(context.selected_objects):
            if o == e or o.get(DISPLAY_TAG) or o.parent == e:
                continue
            if not (o.type in ('MESH', 'LIGHT') or is_replicator_empty(o)):
                continue
            w = o.matrix_world.copy()
            o.parent = e
            o.matrix_parent_inverse = e.matrix_world.inverted()
            o.matrix_world = w
        update_replicator(e)
        return {'FINISHED'}


class OBJECT_OT_replicator_remove_source(bpy.types.Operator):
    bl_idname = "object.replicator_remove_source"
    bl_label = "複製元から外す"
    bl_options = {'REGISTER', 'UNDO'}
    name: StringProperty()

    def execute(self, context):
        e = context.active_object
        o = bpy.data.objects.get(self.name)
        if o is None:
            return {'CANCELLED'}
        col = e.replicator.src_collection if is_replicator_empty(e) else None
        w = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = w
        try:
            o.hide_set(False)
        except Exception:
            pass
        o.hide_render = False
        if col:
            for oo in (o, get_display(o) if is_replicator_empty(o) else None):
                if oo:
                    try:
                        col.objects.unlink(oo)
                    except Exception:
                        pass
        # src_col のみ所属だったので、外したらシーン(ビューレイヤー)へ戻す
        try:
            if o.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(o)
        except Exception:
            pass
        if is_replicator_empty(e):
            update_replicator(e)
        return {'FINISHED'}


class OBJECT_OT_replicator_select_source(bpy.types.Operator):
    bl_idname = "object.replicator_select_source"
    bl_label = "複製元を選択"
    bl_options = {'REGISTER'}
    name: StringProperty()

    def execute(self, context):
        o = bpy.data.objects.get(self.name)
        if o is None:
            return {'CANCELLED'}
        try:
            o.hide_set(False)
        except Exception:
            pass
        for s in context.selected_objects:
            s.select_set(False)
        o.select_set(True)
        context.view_layer.objects.active = o
        return {'FINISHED'}


class OBJECT_OT_replicator_add_field(bpy.types.Operator):
    bl_idname = "object.replicator_add_field"
    bl_label = "フィールドを追加/選択"
    bl_description = "球フィールドのギズモを作成し、ドラッグで影響範囲を動かす"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        e.replicator.field_enable = True
        fo = ensure_field(e)
        update_replicator(e)
        for s in context.selected_objects:
            s.select_set(False)
        fo.select_set(True)
        context.view_layer.objects.active = fo   # 即ドラッグできるよう選択
        return {'FINISHED'}


class OBJECT_OT_d_replicator_set_lang(bpy.types.Operator):
    """このパネルの表示言語を切り替える(日本語/英語)。Blender 全体には影響しない。"""
    bl_idname = "object.d_replicator_set_lang"
    bl_label = "言語"
    bl_options = {'REGISTER', 'INTERNAL'}
    lang: StringProperty(default='JA')

    def execute(self, context):
        try:
            context.window_manager.d_replicator_lang = self.lang
        except Exception:
            pass
        for area in getattr(context.screen, "areas", []) or []:
            area.tag_redraw()
        return {'FINISHED'}


# ---------------------------------------------------------------- UI
_MOD_ICON = {'RANDOM': 'MOD_NOISE', 'STEP': 'IPO_LINEAR', 'TIME': 'TIME'}


def _iter_fcurves(ad):
    """Action のバージョン差(旧 fcurves / 4.4+ スロット式)を吸収して fcurve を列挙。"""
    act = ad.action if ad else None
    if act is None:
        return
    legacy = getattr(act, "fcurves", None)
    if legacy is not None:                         # 〜4.3: action.fcurves
        for fc in legacy:
            yield fc
        return
    slot = getattr(ad, "action_slot", None)        # 4.4+: layers/strips/channelbag
    try:
        for layer in act.layers:
            for strip in layer.strips:
                bag = None
                try:
                    bag = strip.channelbag(slot) if slot is not None else None
                except Exception:
                    bag = None
                bags = [bag] if bag is not None else list(getattr(strip, "channelbags", []))
                for b in bags:
                    for fc in b.fcurves:
                        yield fc
    except Exception:
        return


def _has_key(ob, data_path, frame):
    """現在フレームに data_path のキーがあるか(菱形アイコンの状態用)。"""
    ad = ob.animation_data if ob else None
    if not ad or not ad.action:
        return False
    for fc in _iter_fcurves(ad):
        if fc.data_path == data_path:
            for kp in fc.keyframe_points:
                if abs(kp.co.x - frame) < 0.5:
                    return True
    return False


def _key_row(layout, prop_owner, prop_name, key_ob, data_path, text=None, slider=False):
    """プロパティ + キーフレーム菱形ボタン(現在フレームのキー有無を反映)。
    key_ob = キーを持たせるオブジェクト(Replicator 本体 or フィールドギズモ)。
    ラベルは翻訳(text 指定はそれを、無ければ RNA 表示名を訳す)。"""
    row = layout.row(align=True)
    kw = {}
    if text is not None:
        kw["text"] = t(text)
    else:
        try:
            kw["text"] = t(prop_owner.bl_rna.properties[prop_name].name)
        except Exception:
            pass
    if slider:
        kw["slider"] = True
    row.prop(prop_owner, prop_name, **kw)
    has = _has_key(key_ob, data_path, bpy.context.scene.frame_current)
    op = row.operator("object.replicator_keyframe", text="",
                      icon='KEYFRAME_HLT' if has else 'KEYFRAME')
    op.data_path = data_path
    op.obj_name = key_ob.name
    op.remove = has


class REPLICATOR_UL_modulators(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text="", icon=_MOD_ICON.get(item.mtype, 'DOT'))
        row.prop(item, "name", text="", emboss=False)
        if item.use_field:
            row.label(text="", icon='FORCE_FORCE')
        row.prop(item, "enable", text="")


def _draw_modulator_stack(layout, ob, p):
    box = layout.box()
    _L(box, "モジュレータ", icon='MODIFIER_DATA')
    row = box.row()
    row.template_list("REPLICATOR_UL_modulators", "", p, "modulators", p, "modulator_index", rows=3)
    side = row.column(align=True)
    side.operator("object.replicator_modulator_remove", text="", icon='REMOVE')
    side.separator()
    side.operator("object.replicator_modulator_move", text="", icon='TRIA_UP').direction = 'UP'
    side.operator("object.replicator_modulator_move", text="", icon='TRIA_DOWN').direction = 'DOWN'
    add = box.row(align=True)
    add.operator("object.replicator_modulator_add", text="+ Random", icon='MOD_NOISE').mtype = 'RANDOM'
    add.operator("object.replicator_modulator_add", text="+ Step", icon='IPO_LINEAR').mtype = 'STEP'
    add.operator("object.replicator_modulator_add", text="+ Time", icon='TIME').mtype = 'TIME'
    if 0 <= p.modulator_index < len(p.modulators):
        mi = p.modulator_index
        m = p.modulators[mi]
        base = "replicator.modulators[%d]" % mi
        sub = box.column()
        _P(sub, m, "mtype")
        _key_row(sub, m, "pos", ob, base + ".pos")
        _key_row(sub, m, "rot", ob, base + ".rot")
        _key_row(sub, m, "scale", ob, base + ".scale")
        _key_row(sub, m, "strength", ob, base + ".strength", slider=True)
        if m.mtype == 'RANDOM':
            r = sub.row(align=True)
            _P(r, m, "seed")
            r.operator("object.replicator_modulator_dice", text="", icon='FILE_REFRESH')
        elif m.mtype == 'STEP':
            _P(sub, m, "normalized")
        else:  # TIME
            _key_row(sub, m, "speed", ob, base + ".speed")
            _L(sub, "時間で自動累積(キー不要)。量や速度はキー可", icon='TIME')
        if p.field_enable:
            _P(sub, m, "use_field")


def _draw_field_box(layout, p):
    box = layout.box()
    row = box.row(align=True)
    _P(row, p, "field_enable")
    row.operator("object.replicator_add_field", text="", icon='FORCE_FORCE')
    if p.field_enable:
        fo = get_field(p.id_data)
        if fo is None:
            _L(box, "ギズモ未作成 → 右上の力場ボタンで追加", icon='INFO')
        else:
            ob = p.id_data
            _P(box, p, "field_type")
            _key_row(box, p, "field_radius", ob, "replicator.field_radius")
            _key_row(box, p, "field_falloff", ob, "replicator.field_falloff")
            _P(box, p, "field_invert")
            # ギズモの位置・角度(数値+キー)。位置をキーすればフィールドが掃く動きに
            _key_row(box, fo, "location", fo, "location", text="位置 (m)")
            _key_row(box, fo, "rotation_euler", fo, "rotation_euler", text="角度")
            if p.field_type == 'SPHERE':
                _L(box, "※ 球は回転しても同形。向きは箱/リニア/ノイズで", icon='INFO')
            used = p.step_use_field or any(m.use_field for m in p.modulators)
            if not used:
                _L(box, "※ 段階か各モジュレータの『フィールドで絞る』を ON に", icon='ERROR')


class VIEW3D_PT_replicator(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Replicator"
    bl_label = "Replicator"

    def draw(self, context):
        ob = context.active_object
        # 言語トグル(常に最上部・日英)。Blender 全体ではなくこのパネルだけ切り替わる。
        # 明示的なボタンで描画(prop(expand) はテーマによりラベル無しの単色バーになることがある)。
        cur_lang = getattr(context.window_manager, "d_replicator_lang", 'JA')
        lr = self.layout.row(align=True)
        lr.operator("object.d_replicator_set_lang", text="日本語",
                    depress=(cur_lang == 'JA')).lang = 'JA'
        lr.operator("object.d_replicator_set_lang", text="English",
                    depress=(cur_lang == 'EN')).lang = 'EN'
        # フィールドギズモ選択中: 親 Replicator のフィールド設定を見せる(パネルが空にならない)
        if ob and ob.get(FIELD_TAG) and ob.parent and is_replicator_empty(ob.parent):
            rep = ob.parent
            fcol = self.layout.column()
            _L(fcol, "フィールド(ギズモ選択中)", icon='FORCE_FORCE')
            _O(fcol, "object.replicator_select_source", "Replicator 本体を選択",
               icon='BACK').name = rep.name
            _draw_field_box(fcol, rep.replicator)
            return
        col = self.layout.column()
        _O(col, "object.add_replicator", "Replicator を追加", icon='MESH_GRID')
        if not is_replicator_empty(ob):
            return
        p = ob.replicator

        col.separator()
        _P(col, p, "mode")
        _P(col, p, "count_safety")
        if not p.count_safety:
            _L(col, "⚠ 最大1000。数が多いと Blender が落ちる場合あり", icon='ERROR')
        if p.mode == 'GRID':
            row = col.row(align=True)
            _P(row, p, "count_x")
            _P(row, p, "count_y")
            _P(row, p, "count_z")
            _L(col, "間隔 (cm)")
            _key_row(col, p, "spacing_x", ob, "replicator.spacing_x")
            _key_row(col, p, "spacing_y", ob, "replicator.spacing_y")
            _key_row(col, p, "spacing_z", ob, "replicator.spacing_z")
        elif p.mode == 'LINEAR':
            _P(col, p, "count_x", text="数")
            _L(col, "1ステップの移動 (cm)")
            _key_row(col, p, "spacing_x", ob, "replicator.spacing_x")
            _key_row(col, p, "spacing_y", ob, "replicator.spacing_y")
            _key_row(col, p, "spacing_z", ob, "replicator.spacing_z")
        elif p.mode == 'RADIAL':
            _P(col, p, "count_x", text="数")
            _key_row(col, p, "spacing_x", ob, "replicator.spacing_x", text="半径 (cm)")
        elif p.mode == 'MESH':
            _P(col, p, "mesh_object")
            _P(col, p, "mesh_source")
            if p.mesh_source == 'SURFACE':
                _P(col, p, "count_x", text="数")
                _key_row(col, p, "scatter_amount", ob, "replicator.scatter_amount", slider=True)
                row = col.row(align=True)
                _P(row, p, "scatter_seed")
                row.operator("object.replicator_scatter_dice", text="", icon='FILE_REFRESH')
            _P(col, p, "mesh_align")
            if p.mesh_align:
                _P(col, p, "align_axis")
            _P(col, p, "mesh_use_evaluated")
            ref = p.mesh_object
            if ref is None or ref.type != 'MESH':
                _L(col, "参照メッシュを指定してください", icon='INFO')
            elif p.mesh_source == 'SURFACE':
                shown = int(round(max(int(p.count_x), 0) * p.scatter_amount / 100.0))
                col.label(text="%s: %d / %d (%d%%)"
                          % (t("クローン数"), shown, max(int(p.count_x), 0),
                             int(p.scatter_amount)), icon='DOT')
            elif not p.mesh_use_evaluated:
                cnt = {'VERTS': len(ref.data.vertices),
                       'EDGES': len(ref.data.edges),
                       'FACES': len(ref.data.polygons)}.get(p.mesh_source, 0)
                col.label(text="%s: %d" % (t("クローン数"), cnt), icon='DOT')
            else:
                _L(col, "クローン数: 評価メッシュ依存", icon='DOT')
        elif p.mode == 'SPLINE':
            _P(col, p, "spline_object")
            _P(col, p, "count_x", text="数")
            _P(col, p, "spline_align")
            if p.spline_align:
                _P(col, p, "align_axis")
            ref = p.spline_object
            if ref is None or ref.type != 'CURVE':
                _L(col, "参照スプライン(カーブ)を指定してください", icon='INFO')
            elif len(ref.data.splines) > 1:
                _L(col, "複数スプライン: 最初の1本に配置(現状)", icon='INFO')
        else:  # CIRCLE(円形)
            _P(col, p, "count_x", text="数")
            _key_row(col, p, "radius", ob, "replicator.radius")
            _P(col, p, "radial_plane")
            _P(col, p, "radial_arc")
            _P(col, p, "radial_align")
        _key_row(col, p, "base_scale", ob, "replicator.base_scale")
        _P(col, p, "realize_output")
        if p.realize_output:
            _L(col, "→ Replicator_Display にモディファイヤで全体変形", icon='MODIFIER')
            if any(c.type == 'LIGHT' for c in ob.children):
                _L(col, "⚠ ジオメトリ化ではライトは出ません(OFF で使用)", icon='ERROR')

        box = col.box()
        _L(box, "複製元(参照オブジェクト)")
        _P(box, p, "show_sources", toggle=True)
        srcs = [c for c in ob.children if not c.get(DISPLAY_TAG) and not c.get(FIELD_TAG)]
        if not srcs:
            _L(box, "(なし) 選択して下のボタンで追加", icon='INFO')
        for c in srcs:
            r = box.row(align=True)
            ic = {'MESH': 'OUTLINER_OB_MESH', 'LIGHT': 'OUTLINER_OB_LIGHT'}.get(
                c.type, 'OUTLINER_OB_EMPTY')
            r.label(text=c.name, icon=ic)   # オブジェクト名はそのまま(翻訳しない)
            r.operator("object.replicator_select_source", text="", icon='RESTRICT_SELECT_OFF').name = c.name
            r.operator("object.replicator_remove_source", text="", icon='X').name = c.name
        _O(box, "object.replicator_add_source", "選択を複製元に追加", icon='ADD')

        box = col.box()
        _L(box, "段階トランスフォーム(内蔵)")
        _P(box, p, "step_normalized")
        _key_row(box, p, "step_pos", ob, "replicator.step_pos")
        _key_row(box, p, "step_rot", ob, "replicator.step_rot")
        _key_row(box, p, "step_scale", ob, "replicator.step_scale")
        if p.field_enable:
            _P(box, p, "step_use_field")

        row = col.row(align=True)
        _P(row, p, "dist_seed")
        row.operator("object.replicator_dice", text="", icon='FILE_REFRESH')

        _draw_modulator_stack(col, ob, p)

        _draw_field_box(col, p)

        _O(col, "object.replicator_refresh", "更新", icon='FILE_REFRESH')


# ---------------------------------------------------------------- ハンドラ / 登録
_field_sig = {}        # empty.name -> フィールドの Replicator 相対変換シグネチャ
_ref_sig = {}          # empty.name -> 配置参照(メッシュ/スプライン)のシグネチャ
_field_busy = False    # 再入ガード(自分のメッシュ書込で再呼出されても無視)


def _field_signature(empty, fo):
    """フィールドギズモの「Replicator 相対」変換(4x4)を丸めたタプル。移動/回転/スケール検知用。"""
    m = empty.matrix_world.inverted() @ fo.matrix_world
    return tuple(round(v, 5) for row in m for v in row)


def _placement_ref(p):
    """ライブ追従が要る配置参照オブジェクト(メッシュ/スプライン)。無ければ None。"""
    if p.mode == 'MESH':
        return p.mesh_object
    if p.mode == 'SPLINE':
        return p.spline_object
    return None


def _ref_signature(empty, ref):
    """配置参照: Replicator 相対変換 + 要素数。移動/回転/スケールとトポロジ変化を検知。
    注意: 評価メッシュの『変形のみ(要素数据置)』は検知しない → フレーム送り/更新で反映。"""
    m = empty.matrix_world.inverted() @ ref.matrix_world
    mt = tuple(round(v, 5) for row in m for v in row)
    data = ref.data
    if isinstance(data, bpy.types.Mesh):
        counts = (len(data.vertices), len(data.edges), len(data.polygons))
    elif isinstance(data, bpy.types.Curve):
        counts = (len(data.splines),
                  sum(len(s.bezier_points) + len(s.points) for s in data.splines))
    else:
        counts = (0,)
    return (mt, counts)


@persistent
def _frame_handler(scene, depsgraph):
    # 軽量: 変換のみ。構造(コレクション/可視/ノード)はレンダー/再生中に触らない。
    for ob in scene.objects:
        if is_replicator_empty(ob):
            apply_transforms(ob)
            p = ob.replicator
            fo = get_field(ob)
            if fo is not None:        # アニメ中はここで sig 同期 → depsgraph 側の二重計算を防ぐ
                _field_sig[ob.name] = _field_signature(ob, fo)
            ref = _placement_ref(p)
            if ref is not None:
                _ref_sig[ob.name] = _ref_signature(ob, ref)


@persistent
def _depsgraph_handler(scene, depsgraph):
    """フィールドギズモのドラッグ / 配置参照(メッシュ・スプライン)の移動をライブ再計算。
    書き込むのは表示メッシュだけ=参照側の行列は変わらない → シグネチャ不変 → ループしない。"""
    global _field_busy
    if _field_busy or not depsgraph.id_type_updated('OBJECT'):
        return
    for ob in scene.objects:
        if not is_replicator_empty(ob):
            continue
        p = ob.replicator
        changed = False
        fo = get_field(ob)
        if p.field_enable and fo:
            sig = _field_signature(ob, fo)
            if _field_sig.get(ob.name) != sig:
                _field_sig[ob.name] = sig
                changed = True
        ref = _placement_ref(p)
        if ref is not None:
            rsig = _ref_signature(ob, ref)
            if _ref_sig.get(ob.name) != rsig:
                _ref_sig[ob.name] = rsig
                changed = True
        if changed:
            _field_busy = True
            try:
                apply_transforms(ob)
            finally:
                _field_busy = False


@persistent
def _load_handler(*args):
    """ファイル読込後に旧データをスタックへ移行。"""
    _migrate_all()


# ---------------------------------------------------------------- 翻訳辞書(日本語 → 英語)
# t() が参照(上部で定義)。アドオン内 UI 言語が EN のときだけ使う。Blender 全体の言語は変えない。
_TR_EN = {
    # --- オペレータ ---
    "Replicator を追加": "Add Replicator",
    "選択中のメッシュ/ライト/Replicator を複製元にして Replicator を作成":
        "Create a Replicator using the selected mesh/light/Replicator as source",
    "更新": "Refresh",
    "分配シード振り直し": "Reroll Distribution Seed",
    "複製元の分配シードを引き直して別の組み合わせを探す":
        "Reroll the source distribution seed to find another combination",
    "散布シード振り直し": "Reroll Scatter Seed",
    "面上ランダム散布のシードを引き直して別パターンを探す":
        "Reroll the surface-scatter seed to find another pattern",
    "モジュレータ追加": "Add Modulator",
    "Random / Step / Time のモジュレータをスタックに追加":
        "Add a Random / Step / Time modulator to the stack",
    "モジュレータ削除": "Remove Modulator",
    "モジュレータ並べ替え": "Reorder Modulator",
    "シード振り直し": "Reroll Seed",
    "この Random モジュレータのシードを引き直す": "Reroll this Random modulator's seed",
    "キーフレーム": "Keyframe",
    "現在フレームにこのパラメータのキーを打つ/消す(再生・スクラブでアニメ)":
        "Insert/remove a keyframe for this parameter at the current frame (animate on play/scrub)",
    "選択を複製元に追加": "Add Selected as Source",
    "選択中のメッシュ/ライト/Replicator をこの Replicator の複製元として追加":
        "Add the selected mesh/light/Replicator as a source of this Replicator",
    "複製元から外す": "Remove Source",
    "複製元を選択": "Select Source",
    "フィールドを追加/選択": "Add/Select Field",
    "球フィールドのギズモを作成し、ドラッグで影響範囲を動かす":
        "Create the field gizmo; drag to move its area of influence",
    "言語": "Language",
    "UI 言語を日本語/英語に切り替える(Blender 全体の表示言語を変更)":
        "Switch UI language between Japanese/English (changes Blender's whole interface language)",
    "言語切替に失敗: %s": "Language switch failed: %s",
    "キー操作に失敗: %s": "Keyframe action failed: %s",
    # --- 共通プロパティ ---
    "有効": "Enable",
    "種類": "Type",
    "位置 (cm)": "Position (cm)",
    "回転 (度)": "Rotation (deg)",
    "スケール": "Scale",
    "強度": "Strength",
    "シード": "Seed",
    "正規化(端→端 0→1)": "Normalize (end-to-end 0→1)",
    "速度": "Speed",
    "フィールドで絞る": "Mask by Field",
    "クローンごとにランダム": "Random per clone",
    "クローン列に沿った勾配(0→1)": "Gradient along the clone sequence (0→1)",
    "時間で累積(キーフレーム不要)": "Accumulate over time (no keyframes)",
    # --- 本体プロパティ ---
    "複製元を表示(編集用)": "Show Sources (for editing)",
    "モード": "Mode",
    "グリッド": "Grid",
    "立方格子状": "Cubic lattice",
    "リニア": "Linear",
    "原点から1ステップずつ": "One step at a time from the origin",
    "放射": "Radial",
    "円周状(シンプル・従来)": "Circular (simple, legacy)",
    "円形": "Circle",
    "半径/平面/角度/Align 対応の円配置": "Circular layout with radius/plane/angle/align",
    "メッシュ": "Mesh",
    "任意メッシュの頂点/辺/面の中心に配置(C4D オブジェクトモード相当)":
        "Place on vertices/edges/face centers of any mesh (like C4D Object mode)",
    "スプライン": "Spline",
    "カーブ上に弧長等間隔で配置(C4D スプラインモード相当)":
        "Place evenly along a curve by arc length (like C4D Spline mode)",
    "セーフティ(数を最大100に制限)": "Safety (limit count to 100)",
    "OFF で最大1000まで許容。クローン数が多いと Blender が落ちる場合あり":
        "OFF allows up to 1000. A high clone count may crash Blender",
    "数 X": "Count X",
    "数 Y": "Count Y",
    "数 Z": "Count Z",
    "半径 (cm)": "Radius (cm)",
    "平面": "Plane",
    "角度 (度)": "Angle (deg)",
    "軸を外向きに揃える": "Align Axis Outward",
    "参照メッシュ": "Reference Mesh",
    "配置先": "Placement",
    "頂点": "Vertices",
    "各頂点に配置": "Place on each vertex",
    "辺の中心": "Edge Centers",
    "各辺の中点に配置": "Place at each edge midpoint",
    "面の中心": "Face Centers",
    "各面の中心に配置": "Place at each face center",
    "面上ランダム": "On Surface (random)",
    "面の上にランダム散布(面積重み)": "Random scatter over the surface (area-weighted)",
    "散布率": "Scatter Amount",
    "100%=「数」個が基準。0〜1000%(最大10倍)。"
    "前から増えるので率を変えても既存点は動かない":
        "100% = the 'Count' value. 0–1000% (up to 10x). Points are added from the front, "
        "so changing the rate keeps existing points fixed",
    "法線に揃える": "Align to Normal",
    "クローンの揃え軸を頂点/面の法線方向へ向ける":
        "Point the clone's align axis toward the vertex/face normal",
    "変形後に追従(評価メッシュ)": "Follow Deformed (evaluated mesh)",
    "参照のモディファイヤ/変形を適用した後の形に配置(重い)":
        "Place on the reference's shape after modifiers/deformation (heavy)",
    "揃える軸": "Align Axis",
    "参照スプライン": "Reference Spline",
    "接線に揃える": "Align to Tangent",
    "クローンの揃え軸をカーブの進行方向(接線)へ向ける":
        "Point the clone's align axis along the curve direction (tangent)",
    "基準スケール": "Base Scale",
    "出力をジオメトリ化(Realize)": "Realize Output",
    "位置/ステップ (cm)": "Position/Step (cm)",
    "回転/ステップ (度)": "Rotation/Step (deg)",
    "スケール/ステップ": "Scale/Step",
    "分配シード": "Distribution Seed",
    "フィールド": "Field",
    "球": "Sphere",
    "中心からの距離で減衰": "Falloff by distance from center",
    "箱": "Box",
    "直方体の内側で 1、外で 0": "1 inside the box, 0 outside",
    "矢印(ローカル+Z)方向に沿って減衰": "Falloff along the arrow (local +Z) direction",
    "ノイズ": "Noise",
    "3D ノイズで濃淡(位置/スケールはギズモ基準)":
        "3D noise variation (position/scale from the gizmo)",
    "半径/長さ/スケール (cm)": "Radius/Length/Scale (cm)",
    "球=半径 / 箱=半幅 / リニア=長さ / ノイズ=粒の大きさ":
        "Sphere=radius / Box=half-width / Linear=length / Noise=grain size",
    "減衰幅": "Falloff Width",
    "0=芯だけで急に切れる / 1=滑らかに減衰": "0=hard edge at the core / 1=smooth falloff",
    "反転": "Invert",
    # --- パネルのラベル ---
    "モジュレータ": "Modulators",
    "時間で自動累積(キー不要)。量や速度はキー可":
        "Auto-accumulates over time (no keys). Amount and speed are keyable",
    "ギズモ未作成 → 右上の力場ボタンで追加":
        "No gizmo yet → add it with the force-field button (top right)",
    "位置 (m)": "Position (m)",
    "角度": "Angle",
    "※ 球は回転しても同形。向きは箱/リニア/ノイズで":
        "* A sphere is unchanged by rotation. Use box/linear/noise for direction",
    "※ 段階か各モジュレータの『フィールドで絞る』を ON に":
        "* Turn on 'Mask by Field' on the step or a modulator",
    "フィールド(ギズモ選択中)": "Field (gizmo selected)",
    "Replicator 本体を選択": "Select Replicator",
    "⚠ 最大1000。数が多いと Blender が落ちる場合あり":
        "⚠ Max 1000. A high count may crash Blender",
    "間隔 (cm)": "Spacing (cm)",
    "数": "Count",
    "1ステップの移動 (cm)": "Step Move (cm)",
    "参照メッシュを指定してください": "Please set a reference mesh",
    "クローン数": "Clones",
    "クローン数: 評価メッシュ依存": "Clones: depends on evaluated mesh",
    "参照スプライン(カーブ)を指定してください": "Please set a reference spline (curve)",
    "複数スプライン: 最初の1本に配置(現状)":
        "Multiple splines: only the first is used (for now)",
    "→ Replicator_Display にモディファイヤで全体変形":
        "→ Add modifiers to Replicator_Display for whole-group deform",
    "⚠ ジオメトリ化ではライトは出ません(OFF で使用)":
        "⚠ Lights do not appear when realized (keep OFF)",
    "複製元(参照オブジェクト)": "Sources (reference objects)",
    "(なし) 選択して下のボタンで追加": "(none) select and add with the button below",
    "段階トランスフォーム(内蔵)": "Step Transform (built-in)",
    # --- 言語トグル ---
    "言語": "Language",
}


classes = (
    ReplicatorModulator,   # ReplicatorProps より前に登録(CollectionProperty が参照)
    ReplicatorProps,
    OBJECT_OT_add_replicator,
    OBJECT_OT_replicator_refresh,
    OBJECT_OT_replicator_dice,
    OBJECT_OT_replicator_scatter_dice,
    OBJECT_OT_replicator_add_source,
    OBJECT_OT_replicator_remove_source,
    OBJECT_OT_replicator_select_source,
    OBJECT_OT_replicator_add_field,
    OBJECT_OT_d_replicator_set_lang,
    OBJECT_OT_modulator_add,
    OBJECT_OT_modulator_remove,
    OBJECT_OT_modulator_move,
    OBJECT_OT_modulator_dice,
    OBJECT_OT_replicator_keyframe,
    REPLICATOR_UL_modulators,
    VIEW3D_PT_replicator,
)


def _registered_typename(cls):
    """このクラスが bpy.types に登録される型名。**operator は bl_idname 由来**
    (例 object.replicator_modulator_add → OBJECT_OT_replicator_modulator_add)で
    Python クラス名と異なることがあるため、それを再現する。"""
    idname = getattr(cls, "bl_idname", "") or ""
    if "." in idname:
        cat, name = idname.split(".", 1)
        return "%s_OT_%s" % (cat.upper(), name)
    return cls.__name__


def _safe_unregister_class(cls):
    """同名で登録済みのクラスを**どんな経路でも**解除する(冪等登録の心臓部)。
    背景: PropertyGroup は `bpy.types` に名前で現れず(getattr は None)、別バージョン/reload で
    クラスオブジェクトが別物になると、名前検索では旧登録を消せず『already registered』になる。
    そこで 3 段で確実に消す:
    (1) このオブジェクト自身が登録済みなら直接(同一オブジェクトの ON/OFF)。
    (2) bpy.types に名前で居れば解除(operator は bl_idname 由来名)。
    (3) **親型の Python サブクラスを走査**して『同名 & 登録済み』を全部解除
        (= 旧バージョンが leak させた別オブジェクトの PropertyGroup も掃除 = 更新時対策)。"""
    try:
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    except Exception:
        pass
    for nm in {cls.__name__, _registered_typename(cls)}:
        existing = getattr(bpy.types, nm, None)
        if existing is not None and existing is not cls:
            try:
                bpy.utils.unregister_class(existing)
            except Exception:
                pass
    try:
        for base in cls.__bases__:
            for sub in list(base.__subclasses__()):
                if sub.__name__ == cls.__name__ and getattr(sub, "is_registered", False):
                    try:
                        bpy.utils.unregister_class(sub)
                    except Exception:
                        pass
    except Exception:
        pass


def _purge_handler(handlers, name):
    """同名ハンドラ(前回実行分の別オブジェクト含む)を全て除去 = 二重登録防止。"""
    for h in list(handlers):
        if getattr(h, "__name__", "") == name:
            try:
                handlers.remove(h)
            except Exception:
                pass


def register():
    # 旧登録の取りこぼしに備え、まず PropertyGroup を参照するプロパティを外す
    # (Object.replicator / WM.lang が残っていると PropertyGroup を解除できないため)。
    for owner, attr in ((bpy.types.Object, "replicator"),
                        (bpy.types.WindowManager, "d_replicator_lang")):
        if hasattr(owner, attr):
            try:
                delattr(owner, attr)
            except Exception:
                pass
    # 旧登録を依存の逆順で確実に除去してから入れ直す(Alt+P 再実行・拡張更新に強い)
    for c in reversed(classes):
        _safe_unregister_class(c)
    for c in classes:
        try:
            bpy.utils.register_class(c)
        except Exception:
            _safe_unregister_class(c)      # 取りこぼしがあれば全経路で外して再挑戦
            bpy.utils.register_class(c)
    bpy.types.Object.replicator = PointerProperty(type=ReplicatorProps)
    # アドオン内 UI 言語(Blender 全体の言語は変えない)。WindowManager に保持
    bpy.types.WindowManager.d_replicator_lang = EnumProperty(
        name="言語", description="Replicator パネルの表示言語(Blender 全体には影響しません)",
        items=[('JA', "日本語", "日本語で表示"), ('EN', "English", "Show in English")],
        default='JA')
    for handlers, fn in ((bpy.app.handlers.frame_change_post, _frame_handler),
                         (bpy.app.handlers.depsgraph_update_post, _depsgraph_handler),
                         (bpy.app.handlers.load_post, _load_handler)):
        _purge_handler(handlers, fn.__name__)
        handlers.append(fn)
    try:
        _migrate_all()   # 既存シーンの旧データをスタックへ移行
    except Exception:
        pass


def unregister():
    _purge_handler(bpy.app.handlers.frame_change_post, "_frame_handler")
    _purge_handler(bpy.app.handlers.depsgraph_update_post, "_depsgraph_handler")
    _purge_handler(bpy.app.handlers.load_post, "_load_handler")
    if hasattr(bpy.types.WindowManager, "d_replicator_lang"):
        del bpy.types.WindowManager.d_replicator_lang
    if hasattr(bpy.types.Object, "replicator"):
        del bpy.types.Object.replicator
    for c in reversed(classes):
        _safe_unregister_class(c)


if __name__ == "__main__":
    # テキストエディタで Alt+P 実行用。register() 自体が旧登録を入れ直すので
    # 何度実行しても "already registered" やハンドラ二重化が起きない。
    register()
