# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# D_Replicator — 非破壊の大量複製 & アニメーション アドオン (by Signal88.)
# Copyright (C) 2026 Signal88.
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
# 対象: Blender 4.2 以降(5.1 推奨。開発・動作確認は 5.1、4.2.21 で簡易動作確認済み)

bl_info = {
    "name": "D_Replicator",
    "author": "Signal88.",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),   # 最低バージョン(= manifest と一致)。5.1 推奨・5.1 で開発/検証。
    "location": "View3D > Sidebar > Replicator",
    "description": "オブジェクトを大量に複製してアニメーションする非破壊アドオン (Python 駆動インスタンシング)",
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
    # Reset Children OFF = 複製元オブジェクト自身の変換(スケール/回転)を尊重(相対モード)
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
def _seed(v):
    """シードを numpy RandomState が受け付ける範囲 [0, 2**32-1] に正規化。
    負値(古い保存ファイル等)でも落ちないよう下位31bitを取る。"""
    return int(v) & 0x7fffffff


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
    rng = np.random.RandomState(_seed(seed))
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
    elif p.mode == 'MESH':   # 任意メッシュの頂点/辺/面の中心に配置
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


FALLOFF_NG_PREFIX = "Replicator_Falloff_"   # フィールド減衰カーブを載せる隠しノードグループ名


def _falloff_curve_node(p, create=False):
    """フィールド減衰の『ベジエ曲線』を保持する Float Curve ノードを返す。
    CurveMapping は特定の RNA 上にしか存在しないため、Replicator ごとに
    隠しノードグループ(ShaderNodeTree)へ Float Curve を1個置いてホストする。"""
    name = p.falloff_curve_ng
    ng = bpy.data.node_groups.get(name) if name else None
    if ng is None and create:
        ng = bpy.data.node_groups.new(FALLOFF_NG_PREFIX + p.id_data.name, 'ShaderNodeTree')
        ng.use_fake_user = True               # 参照されなくても保存に残す(永続化)
        p.falloff_curve_ng = ng.name
    if ng is None:
        return None
    node = next((nd for nd in ng.nodes if nd.bl_idname == 'ShaderNodeFloatCurve'), None)
    if node is None and create:
        node = ng.nodes.new("ShaderNodeFloatCurve")
    return node


def _apply_falloff(p, g):
    """生の勾配 g(0..1, 1=芯)を 0..1 の重みへ整形。
    カーブ ON ならベジエ曲線で自由に再マップ、OFF なら従来の smoothstep(減衰幅)。"""
    if getattr(p, "field_use_curve", False):
        node = _falloff_curve_node(p, create=True)
        if node is not None:
            m = node.mapping
            try:
                m.update()
            except Exception:
                pass
            cv = m.curves[0]
            # カーブ評価は Python 呼び出しで重い → 256 点の LUT を1度だけ作り np.interp で引く。
            # (クローン数ぶん m.evaluate するとフィールド操作中に最大1000回/フレームで重くなるため)
            xs = np.linspace(0.0, 1.0, 256)
            lut = np.fromiter((m.evaluate(cv, float(x)) for x in xs),
                              dtype=np.float32, count=256)
            return np.clip(np.interp(g, xs, lut), 0.0, 1.0).astype(np.float32)
    return _shape(g, p.field_falloff)


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
        g = np.clip((R - d) / R, 0.0, 1.0)
    elif ft == 'BOX':
        g = np.clip((R - np.max(np.abs(local), axis=1)) / R, 0.0, 1.0)  # 一番外れた軸で内外
    elif ft == 'LINEAR':
        g = np.clip(local[:, 2] / R, 0.0, 1.0)        # 矢印(ローカル +Z)の先側が強い
    else:  # NOISE
        g = _value_noise(local / R)
    w = np.asarray(_apply_falloff(p, g), dtype=np.float32)  # カーブ or smoothstep で整形
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
        rng = np.random.RandomState(_seed(m.seed))
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
        base_tt = t_sec * m.speed
        if m.time_random > 1e-9:
            # クローンごとに時間係数をランダムに散らす(位相/速度をばらつかせて有機的に)。
            # シードは Random と共用。前から固定なので数を変えても並びが安定。
            rng = np.random.RandomState(_seed(m.seed))
            rf = 1.0 + (rng.random(n).astype(np.float32) * 2.0 - 1.0) * m.time_random
            tta = (base_tt * rf).astype(np.float32)          # (n,)
        else:
            tta = np.full(n, base_tt, dtype=np.float32)      # (n,) 全クローン同じ
        ttc = tta[:, None]                                   # (n,1)
        pos = pos + (mp[None, :] * ttc) * wc
        rot = rot + (mr[None, :] * ttc) * wc
        scale = scale * (1.0 + (msc * tta) * wm)[:, None]
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


def compute_index(p, n, n_sources, perm=None):
    """各クローンがどの複製元を使うか。ランダム分配 or 規則的(順番に繰り返し)。
    perm=複製元の並べ替え写像(ユーザー並びの位置→GN の名前順index)。None なら素の index。"""
    if n_sources <= 1 or n == 0:
        return np.zeros(n, dtype=np.int32)
    if getattr(p, "dist_mode", 'RANDOM') == 'ITERATE':
        positions = np.arange(n) % n_sources                 # 0,1,2,0,1,2,... 規則的
    else:
        positions = np.random.RandomState(_seed(p.dist_seed)).randint(0, n_sources, size=n)
    if perm is not None and len(perm) >= n_sources:
        return perm[positions].astype(np.int32)              # ユーザー並び→GN index へ写像
    return positions.astype(np.int32)


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


def _style_replicator(empty):
    """Replicator 本体の名前をビューポートに表示して見分けやすくする(一度だけ)。
    注: 以前は緑のオブジェクトカラーも付けていたが、既定の色モードでは見えず
    紛らわしいため廃止。フラグを更新して既存 Replicator も既定色(白)へ戻す。"""
    if empty.get("_rep_styled2"):
        return
    empty["_rep_styled2"] = True
    try:
        empty.color = (1.0, 1.0, 1.0, 1.0)   # 既定色(白)。以前の緑オブジェクトカラーを解除
        empty.show_name = True               # 本体名をビューポートに表示
    except Exception:
        pass


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


def _source_pairs(empty):
    """(複製元の子オブジェクト, GN がインスタンス化する実体) のペア一覧。
    メッシュ/ライト → 自身、子 Replicator(入れ子)→ その表示メッシュ。
    UI で並べ替えるのは『子』、GN が並べるのは『実体(名前順)』なので両方を持つ。"""
    out = []
    for c in empty.children:
        if c.get(DISPLAY_TAG) or c.get(FIELD_TAG):
            continue
        if is_replicator_empty(c):
            d = get_display(c)
            if d:
                out.append((c, d))
        elif c.type in ('MESH', 'LIGHT'):
            out.append((c, c))
    return out


def gather_sources(empty):
    """GN がインスタンス化する複製元実体の一覧(メッシュ/ライト/入れ子なら表示メッシュ)。
    ライトは GN インスタンスとして実際に照らす(EEVEE Next / Cycles で確認済)。"""
    return [gn for (_child, gn) in _source_pairs(empty)]


def _sync_source_order(empty):
    """複製元の並び順リスト(source_order)を現在の子に合わせる。
    既存の順番は保ち、増えた分は末尾に追加、消えた分は除去。"""
    p = empty.replicator
    names = [c.name for (c, _gn) in _source_pairs(empty)]
    nameset = set(names)
    for i in reversed(range(len(p.source_order))):           # 消えた複製元を除去
        if p.source_order[i].name not in nameset:
            p.source_order.remove(i)
    have = {it.name for it in p.source_order}
    for nm in names:                                         # 増えた複製元を末尾へ
        if nm not in have:
            p.source_order.add().name = nm


def _ordered_source_children(empty):
    """複製元の子オブジェクトを source_order の順で返す(UI 描画・並べ替え用)。"""
    p = empty.replicator
    by_name = {c.name: c for (c, _gn) in _source_pairs(empty)}
    out = [by_name[it.name] for it in p.source_order if it.name in by_name]
    for nm, c in by_name.items():                            # 取りこぼし(同期前)を末尾へ
        if c not in out:
            out.append(c)
    return out


def _source_permutation(empty):
    """『複製の割り当て順』の写像を返す(長さ=複製元数)。
    GN は実体を**名前順**に並べる(実機確認済)。`perm[ユーザー並びの位置] = GN の名前順index`
    にすることで、UI で並べ替えた順がそのまま複製の順になる。複製元0/1個なら None。"""
    pairs = _source_pairs(empty)
    if len(pairs) <= 1:
        return None
    child_to_gn = {c.name: g.name for (c, g) in pairs}
    gn_pos = {nm: i for i, nm in enumerate(sorted(child_to_gn.values()))}  # GN=名前順
    order = [it.name for it in empty.replicator.source_order if it.name in child_to_gn]
    for c, _g in pairs:                                      # source_order 未同期分は末尾
        if c.name not in order:
            order.append(c.name)
    return np.array([gn_pos[child_to_gn[nm]] for nm in order], dtype=np.int32)


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
    # 編集表示: ON ならメッシュ複製元をシーンにも出す(入れ子の内側表示は除く)。
    # 複製元の位置は**常にロック**(誤って動かさない)。クローン全体の移動は Replicator_Display で。
    if empty.replicator.show_sources:
        scene_col = bpy.context.scene.collection
        for o in want:                              # GN 実体をシーンに出す(メッシュ複製元の可視化)
            if o.get(DISPLAY_TAG):
                continue
            if o.name not in scene_col.objects:
                try:
                    scene_col.objects.link(o)
                except Exception:
                    pass
        for (child, _gn) in _source_pairs(empty):   # 複製元の子(掴める実体)の位置をロック
            try:
                child.lock_location = (True, True, True)
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
    n_src = len(_source_pairs(empty))   # GN がインスタンス化する複製元数。perm と同じ基準にして割当ズレを防ぐ
    pos, rot, scale = compute_clone_data(p, empty)
    idx = compute_index(p, len(pos), n_src, _source_permutation(empty))  # 並べ替え反映
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
    _style_replicator(empty)   # 既存 Replicator にも名前表示を一度だけ適用(緑は解除)
    display = get_display(empty)
    if not display:
        return
    ensure_gn(display)
    sources = gather_sources(empty)
    _sync_source_order(empty)              # 並び順リストを現在の複製元に同期
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
    ('MESH', "メッシュ", "任意メッシュの頂点/辺/面の中心に配置"),
    ('SPLINE', "スプライン", "カーブ上に弧長等間隔で配置"),
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
class ReplicatorSourceItem(bpy.types.PropertyGroup):
    """複製元の並び順を保持する1項目(name=複製元の子オブジェクト名)。
    この順番が『複製の割り当て順』になる(GN は名前順=固定なので、Python で並べ替えを写像)。"""
    name: StringProperty(default="")


class ReplicatorModulator(bpy.types.PropertyGroup):
    """スタックに積む変調器1つ。種類で挙動が変わる(Random/Step/Time)。"""
    name: StringProperty(default="Modulator")
    enable: BoolProperty(name="有効", default=True, update=_upd)
    mtype: EnumProperty(name="種類",
                        items=[('RANDOM', "Random", "クローンごとにランダム"),
                               ('STEP', "Step", "クローン列に沿った勾配(0→1)"),
                               ('TIME', "Time", "時間で累積(キーフレーム不要)")],
                        default='RANDOM', update=_upd)
    pos: FloatVectorProperty(name="位置 (cm)", size=3, subtype='XYZ', step=20,
                             default=(0.0, 0.0, 0.0), update=_upd)
    rot: FloatVectorProperty(name="回転 (度)", size=3, subtype='XYZ',
                             default=(0.0, 0.0, 0.0), update=_upd)
    scale: FloatProperty(name="スケール", default=0.0, update=_upd)
    strength: FloatProperty(name="強度", default=1.0, min=0.0, soft_max=1.0, update=_upd)
    seed: IntProperty(name="シード", default=123456, min=0, update=_upd)  # RANDOM 用(負不可)
    normalized: BoolProperty(name="正規化(端→端 0→1)", default=True, update=_upd)  # STEP 用
    speed: FloatProperty(name="速度", default=1.0, update=_upd)         # TIME 用
    time_random: FloatProperty(name="時間ランダム", default=0.0, min=0.0, soft_max=1.0,  # TIME 用
                               description="クローンごとに時間の進みを乱す(0=全部同じ / 1=±100%でばらつく)。"
                                           "シードは Random と共用",
                               update=_upd)
    use_field: BoolProperty(name="フィールドで絞る", default=False, update=_upd)


class ReplicatorProps(bpy.types.PropertyGroup):
    is_replicator: BoolProperty(default=False)
    src_collection: PointerProperty(type=bpy.types.Collection)
    show_sources: BoolProperty(name="複製元を表示(編集用)", default=False, update=_upd)
    # 複製元の並び順(=複製の割り当て順)。上下で並べ替え。
    source_order: CollectionProperty(type=ReplicatorSourceItem)
    source_index: IntProperty(default=0)
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
    # step はドラッグ感度(既定3=/100で0.03)。間隔/半径は数百cm を扱うので step=20 で速めに
    spacing_x: FloatProperty(name="X", default=200.0, step=20, update=_upd)
    spacing_y: FloatProperty(name="Y", default=200.0, step=20, update=_upd)
    spacing_z: FloatProperty(name="Z", default=200.0, step=20, update=_upd)
    # 円形(放射)モード
    radius: FloatProperty(name="半径 (cm)", default=200.0, min=0.0, step=20, update=_upd)
    radial_plane: EnumProperty(name="平面",
                               items=[('XY', "XY", ""), ('XZ', "XZ", ""), ('YZ', "YZ", "")],
                               default='XY', update=_upd)
    radial_arc: FloatProperty(name="角度 (度)", default=360.0, min=0.0, soft_max=360.0, update=_upd)
    radial_align: BoolProperty(name="軸を外向きに揃える", default=True, update=_upd)
    # メッシュモード(任意メッシュの頂点/辺/面の中心に配置)
    mesh_object: PointerProperty(name="参照メッシュ", type=bpy.types.Object,
                                 poll=_poll_mesh_object, update=_upd)
    mesh_source: EnumProperty(name="配置先", items=_mesh_src_items, update=_upd)  # 既定=先頭(VERTS)
    # 面上ランダム散布(SURFACE)用
    scatter_amount: FloatProperty(name="散布率", default=100.0, min=0.0, max=1000.0,
                                  soft_max=1000.0, subtype='PERCENTAGE',
                                  description="100%=「数」個が基準。0〜1000%(最大10倍)。"
                                              "前から増えるので率を変えても既存点は動かない",
                                  update=_upd)
    scatter_seed: IntProperty(name="シード", default=123456, min=0, update=_upd)
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
    # スプラインモード(カーブ上に弧長等間隔配置)
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
    step_pos: FloatVectorProperty(name="位置/ステップ (cm)", size=3, subtype='XYZ', step=20,
                                  default=(0.0, 0.0, 0.0), update=_upd)
    step_rot: FloatVectorProperty(name="回転/ステップ (度)", size=3, subtype='XYZ',
                                  default=(0.0, 0.0, 0.0), update=_upd)
    step_scale: FloatProperty(name="スケール/ステップ", default=0.0, update=_upd)
    step_use_field: BoolProperty(name="フィールドで絞る", default=False, update=_upd)
    # モジュレータ・スタック(Random / Step / Time を複数積む)
    modulators: CollectionProperty(type=ReplicatorModulator)
    modulator_index: IntProperty(default=0)
    # 複数オブジェクト分配(ランダム / 規則的)
    dist_mode: EnumProperty(
        name="分配", default='RANDOM', update=_upd,
        items=[('RANDOM', "ランダム", "各クローンへランダムに割り当て(シードで変化)"),
               ('ITERATE', "規則的(順番)", "0,1,2,… と順番に繰り返し割り当て(規則的)")])
    dist_seed: IntProperty(name="分配シード", default=123456, min=0, update=_upd)
    # Random(単体・旧/移行用。新規 UI には出さずスタックへ自動移行)
    random_enable: BoolProperty(name="ランダム", default=False, update=_upd)
    random_seed: IntProperty(name="シード", default=123456, min=0, update=_upd)
    random_pos: FloatVectorProperty(name="位置 (cm)", size=3, subtype='XYZ', step=20,
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
    field_radius: FloatProperty(name="半径/長さ/スケール (cm)", default=300.0, min=0.0, step=20,
                                description="球=半径 / 箱=半幅 / リニア=長さ / ノイズ=粒の大きさ",
                                update=_upd_field)
    field_falloff: FloatProperty(name="減衰幅", default=1.0, min=0.0, max=1.0,
                                 description="0=芯だけで急に切れる / 1=滑らかに減衰",
                                 update=_upd)
    # 減衰をベジエ曲線で制御(芯1→境界0 の効き方を自由なカーブで再マップ)
    field_use_curve: BoolProperty(name="カーブで減衰を制御", default=False, update=_upd,
                                  description="ON で減衰の効き方をベジエ曲線で自由に編集できる(減衰幅の代わり)")
    falloff_curve_ng: StringProperty(default="")   # 減衰カーブを載せる隠しノードグループ名
    field_invert: BoolProperty(name="反転", default=False, update=_upd)


# ---------------------------------------------------------------- 生成 / オペレータ
def create_replicator(context, sources=None):
    coll = context.collection or context.scene.collection
    empty = bpy.data.objects.new("Replicator", None)
    empty.empty_display_type = 'PLAIN_AXES'
    coll.objects.link(empty)
    empty.replicator.is_replicator = True
    _style_replicator(empty)   # 本体名を表示して見分けやすく

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
        # 複製元は「複製元を表示」OFF だとビューレイヤー非所属 → そのまま select_set すると
        # 「Object not in View Layer」エラーになる。先に表示を ON にして取り込んでから選択する。
        e = o.parent
        if is_replicator_empty(e) and o.name not in context.view_layer.objects:
            e.replicator.show_sources = True
            update_replicator(e)
        if o.name not in context.view_layer.objects:   # まだ非所属ならシーンへ直接リンク
            try:
                context.scene.collection.objects.link(o)
            except Exception:
                pass
        try:
            o.hide_set(False)
        except Exception:
            pass
        for s in context.selected_objects:
            s.select_set(False)
        try:
            o.select_set(True)
            context.view_layer.objects.active = o
        except Exception as ex:
            self.report({'WARNING'}, "複製元を選択できませんでした: %s" % ex)
            return {'CANCELLED'}
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


class OBJECT_OT_replicator_expand(bpy.types.Operator):
    bl_idname = "object.replicator_expand"
    bl_label = "個別に展開(オブジェクト化)"
    bl_description = ("現在の複製状態を、編集可能な実オブジェクトとして個別に書き出す。"
                     "元の Replicator はそのまま残る(非破壊)。書き出したオブジェクトは"
                     "新しいコレクションに入り、1つずつ自由に編集できる")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return is_replicator_empty(context.active_object)

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        display = get_display(e)
        if display is None:
            return {'CANCELLED'}
        deps = context.evaluated_depsgraph_get()
        new_col = bpy.data.collections.new(e.name + "_Expanded")
        (context.collection or context.scene.collection).children.link(new_col)
        made = 0
        # depsgraph の実インスタンス(=実際に描画されている各クローン)をそのまま実体化。
        # GN の計算結果(位置/回転/スケール/分配)を Blender 自身の評価で正確に再現する。
        for inst in deps.object_instances:
            if not inst.is_instance or inst.parent is None:
                continue
            if inst.parent.original is not display:        # この Replicator の表示由来のみ
                continue
            src = inst.object
            if src is None or src.type not in ('MESH', 'LIGHT', 'CURVE', 'FONT', 'SURFACE'):
                continue
            src_orig = src.original
            new_ob = src_orig.copy()                       # 実オブジェクト(独立して編集可)
            if src_orig.data is not None:
                new_ob.data = src_orig.data.copy()         # データも複製(元と共有しない)
            try:
                new_ob.animation_data_clear()
            except Exception:
                pass
            new_ob.parent = None
            new_col.objects.link(new_ob)
            new_ob.matrix_world = inst.matrix_world.copy() # GN が出した最終ワールド変換
            new_ob.hide_render = False
            try:
                new_ob.hide_set(False)
            except Exception:
                pass
            new_ob.lock_location = (False, False, False)
            made += 1
        if made == 0:
            self.report({'WARNING'}, "展開対象がありません(複製元やクローンを確認)")
            return {'CANCELLED'}
        self.report({'INFO'}, "%d 個のオブジェクトに展開しました(%s)" % (made, new_col.name))
        return {'FINISHED'}


class OBJECT_OT_replicator_dissolve(bpy.types.Operator):
    bl_idname = "object.replicator_dissolve"
    bl_label = "最上位を解除(本体を削除)"
    bl_description = ("入れ子の**最上位 Replicator だけ**を削除し、中身(子 Replicator や複製元)は"
                     "構造を保ったまま独立させる。ワールド位置は維持。最上位の入れ子にだけ出る")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        e = context.active_object
        # 最上位(親が Replicator でない)かつ 子に Replicator を含む(=入れ子の最上位)
        return (is_replicator_empty(e) and not is_replicator_empty(e.parent)
                and any(is_replicator_empty(c) for c in e.children))

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        target = e.users_collection[0] if e.users_collection else context.scene.collection
        disp = get_display(e)
        field = get_field(e)
        src_col = e.replicator.src_collection
        # 子(複製元)を解放: unparent(ワールド維持)+ 位置ロック解除 + 再表示
        released = []
        for c in list(e.children):
            if c is disp or c is field:
                continue
            w = c.matrix_world.copy()
            c.parent = None
            c.matrix_world = w
            try:
                c.lock_location = (False, False, False)
            except Exception:
                pass
            c.hide_render = False
            try:
                c.hide_set(False)
            except Exception:
                pass
            released.append(c)
        # src_col に残る実体(入れ子の内側表示など)を target へ移して孤立を防ぐ
        if src_col:
            for o in list(src_col.objects):
                if o.name not in target.objects:
                    try:
                        target.objects.link(o)
                    except Exception:
                        pass
                try:
                    src_col.objects.unlink(o)
                except Exception:
                    pass
        # 最上位の本体・表示・フィールドを削除
        for o in (disp, field, e):
            if o is not None:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except Exception:
                    pass
        if src_col:
            try:
                bpy.data.collections.remove(src_col)
            except Exception:
                pass
        # 解放した子 Replicator を独立 Replicator として再構築
        active = None
        for c in released:
            if c.name in bpy.data.objects and is_replicator_empty(c):
                update_replicator(c)
                active = active or c
        if active is None:
            active = next((c for c in released if c.name in bpy.data.objects), None)
        if active is not None:
            for s in context.selected_objects:
                s.select_set(False)
            try:
                active.select_set(True)
                context.view_layer.objects.active = active
            except Exception:
                pass
        self.report({'INFO'}, "最上位 Replicator を解除しました(中身は独立)")
        return {'FINISHED'}


class OBJECT_OT_replicator_source_move(bpy.types.Operator):
    bl_idname = "object.replicator_source_move"
    bl_label = "複製元を並べ替え"
    bl_description = "複製元の順番を上下に入れ替える(=複製の割り当て順が変わる)"
    bl_options = {'REGISTER', 'UNDO'}
    name: StringProperty()
    direction: StringProperty(default='UP')

    def execute(self, context):
        e = context.active_object
        if not is_replicator_empty(e):
            return {'CANCELLED'}
        p = e.replicator
        _sync_source_order(e)                              # 念のため同期してから
        i = p.source_order.find(self.name)
        if i < 0:
            return {'CANCELLED'}
        j = i - 1 if self.direction == 'UP' else i + 1
        if 0 <= j < len(p.source_order):
            p.source_order.move(i, j)
            p.source_index = j
            update_replicator(e)
        return {'FINISHED'}


class OBJECT_OT_replicator_select_display(bpy.types.Operator):
    bl_idname = "object.replicator_select_display"
    bl_label = "Replicator_Display を選択"
    bl_description = ("クローン全体の表示オブジェクト(Replicator_Display)を選択。"
                     "これを動かすとクローン全体の位置を編集できる(複製元の位置は触らない)")
    bl_options = {'REGISTER'}

    def execute(self, context):
        e = context.active_object
        d = get_display(e) if is_replicator_empty(e) else None
        if d is None:
            return {'CANCELLED'}
        for s in context.selected_objects:
            s.select_set(False)
        try:
            d.select_set(True)
            context.view_layer.objects.active = d
        except Exception as ex:
            self.report({'WARNING'}, "選択できませんでした: %s" % ex)
            return {'CANCELLED'}
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
    if legacy is not None and len(legacy):         # 〜4.3 は action.fcurves。4.4+ で空ならスロット式へ落とす
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
            _P(sub, m, "time_random", slider=True)
            if m.time_random > 0.0:    # クローンごとの時間ばらつき(シードは Random と共用)
                r = sub.row(align=True)
                _P(r, m, "seed")
                r.operator("object.replicator_modulator_dice", text="", icon='FILE_REFRESH')
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
            _P(box, p, "field_use_curve")
            if p.field_use_curve:        # ベジエ曲線で減衰の効き方を制御
                node = _falloff_curve_node(p, create=True)
                if node is not None:
                    box.template_curve_mapping(node, "mapping")
                _L(box, "横=芯→外(左1→右0)/ 縦=効きの強さ。点を足して自由な減衰に", icon='IPO_BEZIER')
            else:
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
        if p.show_sources:   # 位置は常にロック。全体の移動は Replicator_Display で
            _O(box, "object.replicator_select_display",
               "Replicator_Display を選択(位置編集)", icon='OBJECT_DATA')
        srcs = _ordered_source_children(ob)   # 並び順で描画(↑↓で割り当て順を変更)
        if not srcs:
            _L(box, "(なし) 選択して下のボタンで追加", icon='INFO')
        elif len(srcs) > 1:
            _L(box, "↑↓で複製の割り当て順を変更")
        n_src = len(srcs)
        for i, c in enumerate(srcs):
            r = box.row(align=True)
            ic = {'MESH': 'OUTLINER_OB_MESH', 'LIGHT': 'OUTLINER_OB_LIGHT'}.get(
                c.type, 'OUTLINER_OB_EMPTY')
            r.label(text="%d  %s" % (i, c.name), icon=ic)   # 順番 + 名前(名前は翻訳しない)
            sub = r.row(align=True)
            sub.enabled = n_src > 1
            up = sub.operator("object.replicator_source_move", text="", icon='TRIA_UP')
            up.name, up.direction = c.name, 'UP'
            dn = sub.operator("object.replicator_source_move", text="", icon='TRIA_DOWN')
            dn.name, dn.direction = c.name, 'DOWN'
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

        # 複数複製元の分配(ランダム / 規則的)。複製元が2つ以上のとき意味を持つ。
        _P(col, p, "dist_mode")
        if p.dist_mode == 'RANDOM':
            row = col.row(align=True)
            _P(row, p, "dist_seed")
            row.operator("object.replicator_dice", text="", icon='FILE_REFRESH')

        _draw_modulator_stack(col, ob, p)

        _draw_field_box(col, p)

        # ツール: 個別に展開(実オブジェクト化)/ 最上位を解除(入れ子の最上位だけ削除)
        col.separator()
        trow = col.row(align=True)
        _O(trow, "object.replicator_expand", "個別に展開", icon='OUTLINER_OB_GROUP_INSTANCE')
        # 最上位(親が Replicator でない)かつ 子に Replicator を含む時だけ「最上位を解除」
        if not is_replicator_empty(ob.parent) and any(is_replicator_empty(c) for c in ob.children):
            _O(trow, "object.replicator_dissolve", "最上位を解除", icon='UNLINKED')

        _O(col, "object.replicator_refresh", "更新", icon='FILE_REFRESH')


# ---------------------------------------------------------------- ハンドラ / 登録
_field_sig = {}        # empty.name -> フィールドの Replicator 相対変換シグネチャ
_ref_sig = {}          # empty.name -> 配置参照(メッシュ/スプライン)のシグネチャ
_curve_sig = {}        # empty.name -> 減衰カーブの制御点シグネチャ(編集のライブ反映用)
_field_busy = False    # 再入ガード(自分のメッシュ書込で再呼出されても無視)


def _curve_signature(p):
    """減衰カーブの制御点を丸めたタプル。カーブ編集(点の追加/移動)を検知して再計算する。"""
    if not getattr(p, "field_use_curve", False):
        return None
    node = _falloff_curve_node(p)
    if node is None:
        return None
    try:
        cv = node.mapping.curves[0]
        return tuple((round(pt.location.x, 4), round(pt.location.y, 4), pt.handle_type)
                     for pt in cv.points)
    except Exception:
        return None


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
    # OBJECT(ギズモ/参照の移動)か NODETREE(減衰カーブの編集)の更新時だけ走る。
    if _field_busy or not (depsgraph.id_type_updated('OBJECT')
                           or depsgraph.id_type_updated('NODETREE')):
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
            csig = _curve_signature(p)              # 減衰カーブ編集のライブ反映
            if _curve_sig.get(ob.name) != csig:
                _curve_sig[ob.name] = csig
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
    "任意メッシュの頂点/辺/面の中心に配置":
        "Place on vertices/edges/face centers of any mesh",
    "スプライン": "Spline",
    "カーブ上に弧長等間隔で配置":
        "Place evenly along a curve by arc length",
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
    # --- v0.11 で追加 ---
    "時間ランダム": "Time Random",
    "位置を編集": "Edit Position",
    "分配": "Distribution",
    "カーブで減衰を制御": "Falloff Curve",
    "横=芯→外(左1→右0)/ 縦=効きの強さ。点を足して自由な減衰に":
        "X = core→edge (left 1 → right 0) / Y = strength. Add points for a custom falloff",
    "個別に展開": "Expand to Objects",
    "最上位を解除": "Dissolve Top",
    "Replicator_Display を選択(位置編集)": "Select Replicator_Display (edit position)",
    "↑↓で複製の割り当て順を変更": "↑↓ to reorder clone assignment",
    # --- 言語トグル ---
    "言語": "Language",
}


classes = (
    ReplicatorSourceItem,  # ReplicatorProps より前(CollectionProperty が参照)
    ReplicatorModulator,   # ReplicatorProps より前に登録(CollectionProperty が参照)
    ReplicatorProps,
    OBJECT_OT_add_replicator,
    OBJECT_OT_replicator_refresh,
    OBJECT_OT_replicator_dice,
    OBJECT_OT_replicator_scatter_dice,
    OBJECT_OT_replicator_add_source,
    OBJECT_OT_replicator_remove_source,
    OBJECT_OT_replicator_select_source,
    OBJECT_OT_replicator_select_display,
    OBJECT_OT_replicator_source_move,
    OBJECT_OT_replicator_add_field,
    OBJECT_OT_replicator_expand,
    OBJECT_OT_replicator_dissolve,
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
    _field_sig.clear(); _ref_sig.clear(); _curve_sig.clear()   # 名前キーのキャッシュをリセット(名前再利用での誤判定・リーク防止)
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
    _field_sig.clear(); _ref_sig.clear(); _curve_sig.clear()


if __name__ == "__main__":
    # テキストエディタで Alt+P 実行用。register() 自体が旧登録を入れ直すので
    # 何度実行しても "already registered" やハンドラ二重化が起きない。
    register()
