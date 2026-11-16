"""Scroll-scrubbed hero film (Blender 5.x): one-shot procedural workspace -> JK keycap.

Preview : blender -b -P blender/build_scene.py -- --preview
Final   : blender -b -P blender/build_scene.py -- --final
Subset  : append  --frames START END     or   --list 1,60,160   (single stills)
Output  : --out DIR  (default public/film/desktop/f_0001.webp ...)

World units: 1 unit ~ 0.6 cm (a 1u key pitch is 3.2 units). Z up, camera starts at -Y.
Beats: 1-120 workspace | 121-200 to keyboard | 201-250 launch | 251-330 spin |
       331-400 liquid | 401-480 push-in.

All key-press timing lives in KEY_EVENTS (built by plan_typing); a hand rig can read it.
"""
import colorsys
import math
import random
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Quaternion, Vector

# ----------------------------------------------------------------- TUNABLES
FRAME_END = 480
FPS = 30
LAUNCH_PRESS = 207.0        # JK is pressed once here
POP_FRAME = 213.0           # ...and leaves its switch here
STUDIO_FRAME = 245          # world is exactly BLACK_HEX from here
BLACK_HEX = "0B0B0C"
WALL_HEX = "E9E4DA"
KEY_HEX = "FF4A1C"          # vermilion keycap
LEGEND_HEX = "ECE8DF"
BONE_HEX, MOD_HEX = "E6E1D4", "C9C4B6"
CASE_HEX = "202226"
RIPPLE_DISTANCE = 0.07

PREVIEW_RES, PREVIEW_SAMPLES = (1920, 1080), 64     # EEVEE
FINAL_RES, FINAL_SAMPLES = (1920, 1080), 128        # Cycles + denoise
WEBP_QUALITY = 84

PITCH = 3.2
CAP_BASE, CAP_TOP, CAP_H, CAP_DISH = 3.0, 2.3, 1.5, 0.14
CAP_ROUND = 0.4
CAP_CUTS = 14
LEGEND, LEGEND_SIZE, LEGEND_BOLD = "JK", 1.2, 0.04
INK_HEX = "4B473F"          # printed legends on the bone caps
KEY_SIDE_HEX = "A2260A"
KB_CAP_DISH = 0.2
ENGRAVE_DEPTH = 0.06
LEGEND_FILL = 0.34         # JK height as a fraction of frame height at 480 (whole cap fits)
CAM_SENSOR_W = 36.0
KB_TILT = math.radians(6.0)
KEY_TRAVEL = 0.75
CAP_Z = 3.75                # cap centre above case bottom (rest)
SUN_ENERGY = 3.4
# -------------------------------------------------------------------------

SUN_DIR = Vector((0.80, 0.34, -0.30)).normalized()   # window light travel direction
scene = bpy.context.scene


def hex_lin(h):
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def lin4(h):
    return (*hex_lin(h), 1.0)


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def spl(f, pts):
    """C1 cubic-Hermite through (frame, value) points; zero velocity at both ends."""
    if f <= pts[0][0]:
        return pts[0][1]
    if f >= pts[-1][0]:
        return pts[-1][1]
    i = 0
    while f > pts[i + 1][0]:
        i += 1
    (t0, p0), (t1, p1) = pts[i], pts[i + 1]

    def m(j):
        if j <= 0 or j >= len(pts) - 1:
            return p0 * 0
        return (pts[j + 1][1] - pts[j - 1][1]) / (pts[j + 1][0] - pts[j - 1][0])
    h = t1 - t0
    s = (f - t0) / h
    m0, m1 = m(i) * h, m(i + 1) * h
    return (p0 * (2 * s ** 3 - 3 * s ** 2 + 1) + m0 * (s ** 3 - 2 * s ** 2 + s)
            + p1 * (-2 * s ** 3 + 3 * s ** 2) + m1 * (s ** 3 - s ** 2))


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.worlds, bpy.data.actions, bpy.data.images):
        for d in list(coll):
            coll.remove(d)


def N(nt, kind, x=0, y=0, **props):
    n = nt.nodes.new(kind)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n


def L(nt, a, b):
    nt.links.new(a, b)


def new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.node_tree.nodes.clear()
    return m, m.node_tree


def link(obj, parent=None):
    scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def mk(name, mesh, loc=(0, 0, 0), mat=None, parent=None, smooth=True):
    if mat is not None:
        mesh.materials.append(mat)
    for p in mesh.polygons:
        p.use_smooth = smooth
    o = link(bpy.data.objects.new(name, mesh), parent)
    o.location = loc
    return o


def empty(name, loc=(0, 0, 0), parent=None):
    o = link(bpy.data.objects.new(name, None), parent)
    o.location = loc
    return o


# ------------------------------------------------------------------ MATERIALS
def simple_mat(name, hexc, rough=0.5, metal=0.0, coat=0.0, bump=0.0, bump_scale=200.0, sheen=0.0):
    m, nt = new_mat(name)
    out = N(nt, 'ShaderNodeOutputMaterial', 600, 0)
    b = N(nt, 'ShaderNodeBsdfPrincipled', 300, 0)
    b.inputs['Base Color'].default_value = lin4(hexc)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    b.inputs['Coat Weight'].default_value = coat
    b.inputs['Coat Roughness'].default_value = 0.15
    b.inputs['Sheen Weight'].default_value = sheen
    L(nt, b.outputs['BSDF'], out.inputs['Surface'])
    if bump:
        tc = N(nt, 'ShaderNodeTexCoord', -500, -200)
        nz = N(nt, 'ShaderNodeTexNoise', -300, -200)
        nz.inputs['Scale'].default_value = bump_scale
        nz.inputs['Detail'].default_value = 4.0
        L(nt, tc.outputs['Object'], nz.inputs['Vector'])
        bp = N(nt, 'ShaderNodeBump', 0, -200)
        bp.inputs['Strength'].default_value = bump
        bp.inputs['Distance'].default_value = 0.01
        L(nt, nz.outputs['Fac'], bp.inputs['Height'])
        L(nt, bp.outputs['Normal'], b.inputs['Normal'])
    return m


def emit_mat(name, hexc, strength):
    m, nt = new_mat(name)
    out = N(nt, 'ShaderNodeOutputMaterial', 300, 0)
    e = N(nt, 'ShaderNodeEmission', 0, 0)
    e.inputs['Color'].default_value = lin4(hexc)
    e.inputs['Strength'].default_value = strength
    L(nt, e.outputs['Emission'], out.inputs['Surface'])
    return m


def keycap_material():
    m, nt = new_mat("Keycap")
    out = N(nt, 'ShaderNodeOutputMaterial', 1100, 0)
    bsdf = N(nt, 'ShaderNodeBsdfPrincipled', 800, 0)
    bsdf.inputs['Base Color'].default_value = lin4(KEY_HEX)
    bsdf.inputs['Coat Roughness'].default_value = 0.2
    bsdf.inputs['Sheen Weight'].default_value = 0.0
    bsdf.inputs['Subsurface Weight'].default_value = 0.0
    L(nt, bsdf.outputs['BSDF'], out.inputs['Surface'])
    tc = N(nt, 'ShaderNodeTexCoord', -900, 0)
    noise = N(nt, 'ShaderNodeTexNoise', -650, 250)
    noise.inputs['Scale'].default_value = 12.0
    noise.inputs['Detail'].default_value = 5.0
    L(nt, tc.outputs['Object'], noise.inputs['Vector'])
    # darker, shaded side walls + a deeper tone toward the base
    nrm = N(nt, 'ShaderNodeSeparateXYZ', -900, 450)
    L(nt, tc.outputs['Normal'], nrm.inputs['Vector'])
    nzab = N(nt, 'ShaderNodeMath', -700, 450, operation='ABSOLUTE')
    L(nt, nrm.outputs['Z'], nzab.inputs[0])
    sidem = N(nt, 'ShaderNodeMapRange', -520, 450)
    sidem.inputs['From Min'].default_value = 0.50
    sidem.inputs['From Max'].default_value = 0.93
    sidem.inputs['To Min'].default_value = 1.0
    sidem.inputs['To Max'].default_value = 0.0
    L(nt, nzab.outputs[0], sidem.inputs['Value'])
    zpos = N(nt, 'ShaderNodeSeparateXYZ', -900, 600)
    L(nt, tc.outputs['Object'], zpos.inputs['Vector'])
    zlow = N(nt, 'ShaderNodeMapRange', -520, 600)
    zlow.inputs['From Min'].default_value = -CAP_H / 2
    zlow.inputs['From Max'].default_value = CAP_H / 2 - 0.2
    zlow.inputs['To Min'].default_value = 0.40
    zlow.inputs['To Max'].default_value = 0.0
    L(nt, zpos.outputs['Z'], zlow.inputs['Value'])
    sfac = N(nt, 'ShaderNodeMath', -330, 520, operation='MAXIMUM')
    L(nt, sidem.outputs['Result'], sfac.inputs[0])
    L(nt, zlow.outputs['Result'], sfac.inputs[1])
    sfac2 = N(nt, 'ShaderNodeMath', -160, 520, operation='MULTIPLY', use_clamp=True)
    sfac2.inputs[1].default_value = 0.92
    L(nt, sfac.outputs[0], sfac2.inputs[0])
    cmix = N(nt, 'ShaderNodeMix', 60, 520, data_type='RGBA')
    cmix.inputs[6].default_value = lin4(KEY_HEX)
    cmix.inputs[7].default_value = lin4(KEY_SIDE_HEX)
    L(nt, sfac2.outputs[0], cmix.inputs[0])
    L(nt, cmix.outputs[2], bsdf.inputs['Base Color'])
    mr = N(nt, 'ShaderNodeMapRange', -400, 250)
    mr.inputs['To Min'].default_value = 0.5
    mr.inputs['To Max'].default_value = 0.68
    L(nt, noise.outputs['Fac'], mr.inputs['Value'])
    gloss = N(nt, 'ShaderNodeValue', -400, 50)
    gloss.label = "Gloss"
    mix = N(nt, 'ShaderNodeMix', -100, 200, data_type='FLOAT')
    L(nt, gloss.outputs[0], mix.inputs[0])
    L(nt, mr.outputs['Result'], mix.inputs[2])
    mix.inputs[3].default_value = 0.2
    L(nt, mix.outputs[0], bsdf.inputs['Roughness'])
    coat = N(nt, 'ShaderNodeMath', -100, -50, operation='MULTIPLY')
    coat.inputs[1].default_value = 0.4
    L(nt, gloss.outputs[0], coat.inputs[0])
    L(nt, coat.outputs[0], bsdf.inputs['Coat Weight'])
    wave = N(nt, 'ShaderNodeTexWave', -650, -250, wave_type='RINGS',
             rings_direction='SPHERICAL', wave_profile='SIN')
    wave.inputs['Scale'].default_value = 2.0
    wave.inputs['Distortion'].default_value = 0.0
    wave.inputs['Detail'].default_value = 0.0
    L(nt, tc.outputs['Object'], wave.inputs['Vector'])
    amt = N(nt, 'ShaderNodeValue', -400, -450)
    amt.label = "RippleAmt"
    bump = N(nt, 'ShaderNodeBump', -100, -250)
    bump.inputs['Distance'].default_value = RIPPLE_DISTANCE
    L(nt, wave.outputs['Fac'], bump.inputs['Height'])
    sepz = N(nt, 'ShaderNodeSeparateXYZ', -650, -450)
    L(nt, tc.outputs['Object'], sepz.inputs['Vector'])
    zmask = N(nt, 'ShaderNodeMapRange', -400, -550)
    zmask.inputs['From Min'].default_value = CAP_H / 2 - CAP_DISH - 0.18
    zmask.inputs['From Max'].default_value = CAP_H / 2 - CAP_DISH - 0.06
    L(nt, sepz.outputs['Z'], zmask.inputs['Value'])
    amask = N(nt, 'ShaderNodeMath', -250, -450, operation='MULTIPLY')
    L(nt, amt.outputs[0], amask.inputs[0])
    L(nt, zmask.outputs['Result'], amask.inputs[1])
    L(nt, amask.outputs[0], bump.inputs['Strength'])
    micro = N(nt, 'ShaderNodeTexNoise', -400, -650)
    micro.inputs['Scale'].default_value = 220.0
    micro.inputs['Detail'].default_value = 3.0
    L(nt, tc.outputs['Object'], micro.inputs['Vector'])
    bump2 = N(nt, 'ShaderNodeBump', 300, -250)
    bump2.inputs['Strength'].default_value = 0.25
    bump2.inputs['Distance'].default_value = 0.004
    L(nt, micro.outputs['Fac'], bump2.inputs['Height'])
    L(nt, bump.outputs['Normal'], bump2.inputs['Normal'])
    L(nt, bump2.outputs['Normal'], bsdf.inputs['Normal'])
    return m, gloss, amt, wave


def legend_material():
    return simple_mat("Legend", LEGEND_HEX, rough=0.5)


def ink_material():
    return simple_mat("Ink", INK_HEX, rough=0.42)


def board_cap_material(name, hexc):
    """Bone cap: per-object tone/roughness variation via Object Info > Random, fine PBT grain."""
    m, nt = new_mat(name)
    out = N(nt, 'ShaderNodeOutputMaterial', 900, 0)
    b = N(nt, 'ShaderNodeBsdfPrincipled', 600, 0)
    b.inputs['Sheen Weight'].default_value = 0.25
    b.inputs['Specular IOR Level'].default_value = 0.45
    L(nt, b.outputs['BSDF'], out.inputs['Surface'])
    oi = N(nt, 'ShaderNodeObjectInfo', -600, 200)
    rv = N(nt, 'ShaderNodeMapRange', -380, 250)
    rv.inputs['To Min'].default_value = 0.90
    rv.inputs['To Max'].default_value = 1.04
    L(nt, oi.outputs['Random'], rv.inputs['Value'])
    col = N(nt, 'ShaderNodeCombineColor', -160, 250)
    for k in ('Red', 'Green', 'Blue'):
        L(nt, rv.outputs['Result'], col.inputs[k])
    base = N(nt, 'ShaderNodeMix', 120, 200, data_type='RGBA', blend_type='MULTIPLY')
    base.inputs[0].default_value = 1.0
    base.inputs[6].default_value = lin4(hexc)
    L(nt, col.outputs['Color'], base.inputs[7])
    L(nt, base.outputs[2], b.inputs['Base Color'])
    rr = N(nt, 'ShaderNodeMapRange', -380, 0)
    rr.inputs['To Min'].default_value = 0.42
    rr.inputs['To Max'].default_value = 0.60
    L(nt, oi.outputs['Random'], rr.inputs['Value'])
    L(nt, rr.outputs['Result'], b.inputs['Roughness'])
    tc = N(nt, 'ShaderNodeTexCoord', -700, -250)
    nz = N(nt, 'ShaderNodeTexNoise', -480, -250)
    nz.inputs['Scale'].default_value = 260.0
    nz.inputs['Detail'].default_value = 3.0
    L(nt, tc.outputs['Object'], nz.inputs['Vector'])
    bp = N(nt, 'ShaderNodeBump', 300, -250)
    bp.inputs['Strength'].default_value = 0.18
    bp.inputs['Distance'].default_value = 0.004
    L(nt, nz.outputs['Fac'], bp.inputs['Height'])
    L(nt, bp.outputs['Normal'], b.inputs['Normal'])
    return m


def desk_material():
    """Light oak: flowing grain bands + fine fibres, plank seams along X, per-plank tone."""
    PW = 26.0
    m, nt = new_mat("OakDesk")
    out = N(nt, 'ShaderNodeOutputMaterial', 1600, 0)
    tc = N(nt, 'ShaderNodeTexCoord', -1500, 0)
    mp = N(nt, 'ShaderNodeMapping', -1300, 100)
    mp.inputs['Scale'].default_value = (0.035, 1.0, 1.0)       # long along X
    L(nt, tc.outputs['Object'], mp.inputs['Vector'])
    sep = N(nt, 'ShaderNodeSeparateXYZ', -1300, -250)
    L(nt, tc.outputs['Object'], sep.inputs['Vector'])
    div = N(nt, 'ShaderNodeMath', -1100, -250, operation='DIVIDE')
    div.inputs[1].default_value = PW
    L(nt, sep.outputs['Y'], div.inputs[0])
    pid = N(nt, 'ShaderNodeMath', -950, -350, operation='FLOOR')
    L(nt, div.outputs[0], pid.inputs[0])
    wn = N(nt, 'ShaderNodeTexWhiteNoise', -800, -350, noise_dimensions='1D')
    L(nt, pid.outputs[0], wn.inputs['W'])
    ph = N(nt, 'ShaderNodeMath', -650, -350, operation='MULTIPLY')
    ph.inputs[1].default_value = 40.0
    L(nt, wn.outputs['Value'], ph.inputs[0])
    wave = N(nt, 'ShaderNodeTexWave', -900, 200, wave_type='BANDS', bands_direction='Y',
             wave_profile='SAW')
    wave.inputs['Scale'].default_value = 1.1
    wave.inputs['Distortion'].default_value = 9.0
    wave.inputs['Detail'].default_value = 2.5
    wave.inputs['Detail Scale'].default_value = 1.4
    L(nt, mp.outputs['Vector'], wave.inputs['Vector'])
    L(nt, ph.outputs[0], wave.inputs['Phase Offset'])
    fib = N(nt, 'ShaderNodeTexNoise', -900, -50)
    fib.inputs['Scale'].default_value = 34.0
    fib.inputs['Detail'].default_value = 5.0
    fib.inputs['Roughness'].default_value = 0.6
    L(nt, mp.outputs['Vector'], fib.inputs['Vector'])
    mixg = N(nt, 'ShaderNodeMix', -650, 100, data_type='FLOAT')
    mixg.inputs[0].default_value = 0.42
    L(nt, wave.outputs['Fac'], mixg.inputs[2])
    L(nt, fib.outputs['Fac'], mixg.inputs[3])
    ramp = N(nt, 'ShaderNodeValToRGB', -400, 100)
    ramp.color_ramp.elements[0].position = 0.30
    ramp.color_ramp.elements[0].color = lin4("B88C58")
    ramp.color_ramp.elements[1].position = 0.70
    ramp.color_ramp.elements[1].color = lin4("DDC49B")
    L(nt, mixg.outputs[0], ramp.inputs['Fac'])
    tone = N(nt, 'ShaderNodeMix', -150, 100, data_type='RGBA', blend_type='MULTIPLY')
    tone.inputs[0].default_value = 0.35
    L(nt, ramp.outputs['Color'], tone.inputs[6])
    tmap = N(nt, 'ShaderNodeMapRange', -400, -350)
    tmap.inputs['To Min'].default_value = 0.88
    tmap.inputs['To Max'].default_value = 1.06
    L(nt, wn.outputs['Value'], tmap.inputs['Value'])
    tcol = N(nt, 'ShaderNodeCombineColor', -150, -350)
    for k in ('Red', 'Green', 'Blue'):
        L(nt, tmap.outputs['Result'], tcol.inputs[k])
    L(nt, tcol.outputs['Color'], tone.inputs[7])
    # seams
    fr = N(nt, 'ShaderNodeMath', -950, -550, operation='FRACT')
    L(nt, div.outputs[0], fr.inputs[0])
    sb = N(nt, 'ShaderNodeMath', -800, -550, operation='SUBTRACT')
    sb.inputs[1].default_value = 0.5
    L(nt, fr.outputs[0], sb.inputs[0])
    ab = N(nt, 'ShaderNodeMath', -650, -550, operation='ABSOLUTE')
    L(nt, sb.outputs[0], ab.inputs[0])
    seam = N(nt, 'ShaderNodeMapRange', -500, -550)
    seam.inputs['From Min'].default_value = 0.4985
    seam.inputs['From Max'].default_value = 0.4998
    seam.inputs['To Max'].default_value = 0.35
    L(nt, ab.outputs[0], seam.inputs['Value'])
    sc = N(nt, 'ShaderNodeMix', 100, 100, data_type='RGBA', blend_type='MULTIPLY')
    sc.inputs[7].default_value = (0.3, 0.22, 0.14, 1.0)
    L(nt, seam.outputs['Result'], sc.inputs[0])
    L(nt, tone.outputs[2], sc.inputs[6])
    # roughness + bump
    rmr = N(nt, 'ShaderNodeMapRange', -400, -150)
    rmr.inputs['To Min'].default_value = 0.40
    rmr.inputs['To Max'].default_value = 0.62
    L(nt, fib.outputs['Fac'], rmr.inputs['Value'])
    bump = N(nt, 'ShaderNodeBump', 300, -250)
    bump.inputs['Strength'].default_value = 0.35
    bump.inputs['Distance'].default_value = 0.02
    L(nt, fib.outputs['Fac'], bump.inputs['Height'])
    wood = N(nt, 'ShaderNodeBsdfPrincipled', 800, 100)
    wood.inputs['Specular IOR Level'].default_value = 0.45
    L(nt, sc.outputs[2], wood.inputs['Base Color'])
    L(nt, rmr.outputs['Result'], wood.inputs['Roughness'])
    L(nt, bump.outputs['Normal'], wood.inputs['Normal'])
    L(nt, wood.outputs['BSDF'], out.inputs['Surface'])
    return m


# ------------------------------------------------------------------- GEOMETRY
def build_keycap_mesh(wu=1.0, cuts=CAP_CUTS, dish=CAP_DISH):
    """Rounded, dished keycap. wu = width in key units (stretches X only)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    sx = ((wu * PITCH) - (PITCH - CAP_BASE)) / CAP_BASE
    for v in bm.verts:
        t = v.co.z + 0.5
        u, w = v.co.x * 2, v.co.y * 2
        cu = u * math.sqrt(max(0.0, 1 - w * w / 2))
        cw = w * math.sqrt(max(0.0, 1 - u * u / 2))
        u2, w2 = u + (cu - u) * CAP_ROUND, w + (cw - w) * CAP_ROUND
        s = CAP_BASE + (CAP_TOP - CAP_BASE) * t
        x, y = u2 * s / 2, w2 * s / 2
        z = t * CAP_H - CAP_H / 2
        if t > 0.9999:
            nx, ny = x / (CAP_TOP / 2), y / (CAP_TOP / 2)
            z -= dish * (1 - (nx * nx + ny * ny) / 2)
        v.co = (x * sx, y, z)
    me = bpy.data.meshes.new("KeycapMesh")
    bm.to_mesh(me)
    bm.free()
    return me


def baked(obj, name):
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    me.name = name
    return me


def baked_cap(wu):
    me = build_keycap_mesh(wu, cuts=9, dish=KB_CAP_DISH)
    ob = link(bpy.data.objects.new("tmp", me))
    bev = ob.modifiers.new("Bevel", 'BEVEL')
    bev.width, bev.segments = 0.075, 3
    bev.limit_method, bev.angle_limit = 'ANGLE', math.radians(32)
    bpy.context.view_layer.update()
    out = baked(ob, f"Cap{wu}")
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    return out


def text_mesh(extrude, name):
    cu = bpy.data.curves.new(name, 'FONT')
    cu.body = LEGEND
    cu.size = LEGEND_SIZE
    cu.align_x = 'CENTER'
    cu.align_y = 'CENTER'
    cu.extrude = extrude
    cu.resolution_u = 32
    cu.offset = LEGEND_BOLD
    cu.fill_mode = 'BOTH'
    ob = link(bpy.data.objects.new(name, cu))
    bpy.context.view_layer.update()
    me = baked(ob, name + "Mesh")
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    xs = [v.co.x for v in me.vertices]
    ys = [v.co.y for v in me.vertices]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    me.transform(Matrix.Translation((-cx, -cy, 0)))
    for p in me.polygons:
        p.use_smooth = False
    return me, max(ys) - min(ys)



# ---------------------------------------------------------- KEY LEGENDS (printed)
SHIFTED = {'`': '~', '1': '!', '2': '@', '3': '#', '4': '$', '5': '%', '6': '^', '7': '&', '8': '*',
           '9': '(', '0': ')', '-': '_', '=': '+', '[': '{', ']': '}', chr(92): '|', ';': ':', "'": '"',
           ',': '<', '.': '>', '/': '?'}
MOD_TEXT = {'esc': 'Esc', 'prt': 'PrtSc', 'del': 'Del', 'home': 'Home', 'bksp': 'Backspace', 'pgup': 'PgUp',
            'tab': 'Tab', 'pgdn': 'PgDn', 'caps': 'Caps', 'enter': 'Enter', 'end': 'End', 'lsh': 'Shift',
            'rsh': 'Shift', 'ins': 'Ins', 'lctl': 'Ctrl', 'win': 'Win', 'lalt': 'Alt', 'ralt': 'Alt',
            'fn': 'Fn', 'rctl': 'Ctrl'}
ARROWS = {'up': 0.0, 'left': 90.0, 'down': 180.0, 'right': 270.0}
_TXT_CACHE = {}


def flat_text(text, size, align='CENTER'):
    """Baseline-anchored flat text outline fill -> ([(x, y)], [faces]); cached."""
    key = (text, size, align)
    if key in _TXT_CACHE:
        return _TXT_CACHE[key]
    cu = bpy.data.curves.new("lg", 'FONT')
    cu.body, cu.size = text, size
    cu.align_x, cu.align_y = align, 'BOTTOM_BASELINE'
    cu.resolution_u = 12
    cu.fill_mode = 'FRONT'
    ob = link(bpy.data.objects.new("lg", cu))
    bpy.context.view_layer.update()
    me = baked(ob, "lg_mesh")
    bpy.data.objects.remove(ob)
    bpy.data.curves.remove(cu)
    out = ([(v.co.x, v.co.y) for v in me.vertices], [tuple(p.vertices) for p in me.polygons])
    bpy.data.meshes.remove(me)
    _TXT_CACHE[key] = out
    return out


def cap_height(size):
    vs, _ = flat_text("H", size)
    return max(v[1] for v in vs) - min(v[1] for v in vs)


def arrow_shape(angle_deg, size):
    a = math.radians(angle_deg)
    pts = [(0, size * 0.55), (-size * 0.5, -size * 0.35), (size * 0.5, -size * 0.35)]
    pts = [(x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)) for x, y in pts]
    return pts, [(0, 1, 2)]


def legend_parts(kid, wu):
    """-> list of (verts2d, faces) in key-local XY, laid out for the top face."""
    half = (wu * PITCH - 0.9) / 2.0
    parts = []

    def put(text, size, cx, base, align='CENTER', maxw=None):
        vs, fs = flat_text(text, size, align)
        if not vs:
            return
        xs = [v[0] for v in vs]
        w = max(xs) - min(xs)
        k = 1.0
        if maxw and w > maxw:
            k = maxw / w
        parts.append(([(cx + v[0] * k, base + v[1] * k) for v in vs], fs))

    if kid in ARROWS:
        parts.append(arrow_shape(ARROWS[kid], 0.8))
    elif kid in SHIFTED:
        sz = 0.78
        ch = cap_height(sz)
        put(SHIFTED[kid], sz, 0.0, 0.12)
        put(kid, sz, 0.0, -0.12 - ch)
    elif kid in ALPHA:
        sz = 1.02
        put(kid.upper() if kid.isalpha() else kid, sz, 0.0, -cap_height(sz) / 2)
    elif kid.startswith('f') and kid[1:].isdigit():
        sz = 0.62
        put(kid.upper(), sz, 0.0, -cap_height(sz) / 2, maxw=half * 1.7)
    elif kid in MOD_TEXT:
        sz = 0.5
        base = -cap_height(sz) / 2
        if wu < 1.2:
            put(MOD_TEXT[kid], sz, 0.0, base, maxw=half * 1.75)
        else:
            put(MOD_TEXT[kid], sz, -half + 0.32, base, 'LEFT')
    return parts


def project_legend(parts, tree, name, lift=0.012):
    bm = bmesh.new()
    top_default = CAP_H / 2 - KB_CAP_DISH
    for vs, fs in parts:
        vm = [bm.verts.new((x, y, 0.0)) for x, y in vs]
        for f in fs:
            try:
                bm.faces.new([vm[i] for i in f])
            except ValueError:
                pass
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=2, use_grid_fill=False)
    for v in bm.verts:
        hit = tree.ray_cast((v.co.x, v.co.y, 4.0), (0, 0, -1), 8.0)
        v.co.z = (hit[0].z if hit and hit[0] is not None else top_default) + lift
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    return me


def box_mesh(name, size, bevel=0.0, plan_r=0.0, seg=3, off=(0, 0, 0)):
    """Cuboid (centred + off) with optional rounded vertical corners and bevelled edges, baked."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2])) + Vector(off)
    if plan_r > 0:
        vert = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > size[2] * 0.5]
        bmesh.ops.bevel(bm, geom=vert, offset=plan_r, segments=6, profile=0.5, affect='EDGES')
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if bevel > 0:
        ob = link(bpy.data.objects.new("tmp", me))
        b = ob.modifiers.new("B", 'BEVEL')
        b.width, b.segments, b.limit_method, b.angle_limit = bevel, seg, 'ANGLE', math.radians(30)
        bpy.context.view_layer.update()
        me2 = baked(ob, name)
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
        me = me2
    return me


def rect_mesh(name, rects, z=0.0):
    """rects: (x0, y0, x1, y1) in screen space -> one flat mesh."""
    bm = bmesh.new()
    for x0, y0, x1, y1 in rects:
        vs = [bm.verts.new((x0, y0, z)), bm.verts.new((x1, y0, z)),
              bm.verts.new((x1, y1, z)), bm.verts.new((x0, y1, z))]
        bm.faces.new(vs)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


# ----------------------------------------------------------------- KEYBOARD
ROWS = [
    [("esc", 1)] + [(f"f{i}", 1) for i in range(1, 13)] + [("prt", 1), ("del", 1), ("home", 1)],
    [("`", 1)] + [(c, 1) for c in "1234567890-="] + [("bksp", 2), ("pgup", 1)],
    [("tab", 1.5)] + [(c, 1) for c in "qwertyuiop[]"] + [("\\", 1.5), ("pgdn", 1)],
    [("caps", 1.75)] + [(c, 1) for c in "asdfghjkl;'"] + [("enter", 2.25), ("end", 1)],
    [("lsh", 2.25)] + [(c, 1) for c in "zxcvbnm,./"] + [("rsh", 1.75), ("up", 1), ("ins", 1)],
    [("lctl", 1.25), ("win", 1.25), ("lalt", 1.25), ("space", 6.25), ("ralt", 1), ("fn", 1),
     ("rctl", 1), ("left", 1), ("down", 1), ("right", 1)],
]
ROW_TILT = [9, 5, 1, -2, -5, -7]       # degrees about X (back row faces the typist)
HERO_KEY = "l"                         # the vermilion JK key sits on this switch
ALPHA = set("abcdefghijklmnopqrstuvwxyz0123456789`-=[]\\;',./")


def layout():
    keys = {}
    for r, row in enumerate(ROWS):
        x = -8.0 * PITCH
        for kid, wu in row:
            keys[kid] = (x + wu * PITCH / 2, PITCH * (2.5 - r), r, wu)
            x += wu * PITCH
    return keys


KEYS = layout()
KB_W, KB_D = 16 * PITCH + 3.2, 6 * PITCH + 3.2
KB_Z0 = (KB_D / 2) * math.sin(KB_TILT)
KB_M = Matrix.Translation((0, 0, KB_Z0)) @ Matrix.Rotation(KB_TILT, 4, 'X')
hx, hy, hr, _ = KEYS[HERO_KEY]
HERO_LOCAL = Matrix.Translation((hx, hy, CAP_Z)) @ Matrix.Rotation(math.radians(ROW_TILT[hr]), 4, 'X')
HERO_WORLD = KB_M @ HERO_LOCAL
JK0 = HERO_WORLD.translation.copy()
Q_KB = HERO_WORLD.to_quaternion()


# ---- typing plan: THE single data table of key presses (frame, key id, hold frames)
def plan_typing():
    rng = random.Random(11)
    text = "thequickbrownfoxjumpsoverthelazydogpackmyboxwithfivedozenliquorjugs"
    ev, toks, caret = [], [], []
    palette = ["kw", "id", "fn", "str", "num", "id", "id", "cm"]
    t, ci, line = 4.0, 0, 8
    indent = 2.4
    burst = rng.randint(5, 10)
    caret.append((0.0, indent, line))

    def advance():
        nonlocal t, burst
        if burst > 0:
            t += rng.uniform(2.4, 4.6)
            burst -= 1
        else:
            t += rng.uniform(9.0, 24.0)
            burst = rng.randint(5, 12)

    while t < 203 and line < 19:
        x = indent
        for k in range(rng.randint(3, 6)):
            if t >= 203:
                break
            key = text[ci % len(text)]
            ci += 1
            w = rng.uniform(2.4, 8.5)
            ev.append((round(t, 2), key, rng.uniform(1.2, 3.0)))
            toks.append(dict(t=t, line=line, x0=x, w=w, col=rng.choice(palette)))
            x += w
            caret.append((t, x, line))
            x += 1.2
            advance()
            if rng.random() < 0.3 and t < 203:
                ev.append((round(t, 2), "space", rng.uniform(1.5, 3.0)))
                caret.append((t, x, line))
                advance()
        if t < 203:
            ev.append((round(t, 2), "enter", rng.uniform(1.5, 2.8)))
            line += 1
            indent = rng.choice([2.4, 2.4, 4.8, 7.2])
            caret.append((t, indent, line))
            advance()
    return ev, toks, caret


KEY_EVENTS, TOKENS, CARET = plan_typing()
KEY_EVENTS.append((LAUNCH_PRESS, HERO_KEY, 2.0))     # the one launch press


def press_profile(dt, hold):
    if dt < 0:
        return 0.0
    if dt < 1.6:
        return ease(dt / 1.6)
    if dt < 1.6 + hold:
        return 1.0
    r = (dt - 1.6 - hold) / 3.0
    if r < 1:
        return 1 - ease(r)
    if r < 2:
        return -0.07 * math.sin(math.pi * (r - 1))
    return 0.0


def depth(key, f):
    d = 0.0
    for t, k, h in KEY_EVENTS:
        if k == key:
            d = max(d, press_profile(f - t, h))
    return d


def build_keyboard(parent, cap_mats):
    from mathutils.bvhtree import BVHTree
    kb = empty("Keyboard", (0, 0, KB_Z0), parent)
    kb.rotation_euler = (KB_TILT, 0, 0)
    case_mat = simple_mat("Case", CASE_HEX, rough=0.42, metal=0.15, coat=0.1, bump=0.15, bump_scale=60)
    case = mk("Case", box_mesh("Case", (KB_W, KB_D, 2.4), bevel=0.55, plan_r=1.2, seg=4,
                               off=(0, 0, 1.2)), mat=case_mat, parent=kb)
    # brushed plate visible between the caps
    plate_mat = simple_mat("Plate", "7A7F88", rough=0.38, metal=0.85, bump=0.2, bump_scale=300)
    mk("Plate", box_mesh("Plate", (KB_W - 2.2, KB_D - 2.2, 0.35), bevel=0.08, seg=2, off=(0, 0, 2.375)),
       mat=plate_mat, parent=kb)
    # switch bodies (one merged mesh, smoky grey) under the caps
    bm = bmesh.new()
    for kid, (x, y, r, wu) in KEYS.items():
        for sx in ([0] if wu < 5 else [-wu * PITCH * 0.3, 0, wu * PITCH * 0.3]):
            bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((x + sx, y, 2.6)) @
                                  Matrix.Diagonal((1.5, 1.5, 0.8, 1.0)))
    me = bpy.data.meshes.new("Switches")
    bm.to_mesh(me)
    bm.free()
    mk("Switches", me, mat=simple_mat("Sw", "23262B", rough=0.5), parent=kb, smooth=False)
    # the JK switch: housing + cross stem, revealed when the cap leaves
    hx_, hy_, hr_, _w = KEYS[HERO_KEY]
    hsw = mk("HeroSwitch", box_mesh("HeroSwitch", (2.05, 2.05, 0.7), bevel=0.12, seg=2, off=(0, 0, 2.65)),
             (hx_, hy_, 0), simple_mat("SwHousing", "3C4048", rough=0.38, coat=0.2), kb)
    stem_root = empty("HeroStem", (hx_, hy_, 0.0), kb)
    stem_mat = simple_mat("Stem", "E8E2D2", rough=0.35, coat=0.15)
    mk("StemA", box_mesh("StemA", (1.25, 0.42, 0.95), bevel=0.05, seg=2, off=(0, 0, 3.45)), mat=stem_mat,
       parent=stem_root)
    mk("StemB", box_mesh("StemB", (0.42, 1.25, 0.95), bevel=0.05, seg=2, off=(0, 0, 3.45)), mat=stem_mat,
       parent=stem_root)
    mesh_cache, tree_cache = {}, {}
    key_objs = {}
    ink = ink_material()
    rng = random.Random(23)
    for kid, (x, y, r, wu) in KEYS.items():
        if kid == HERO_KEY:
            continue
        isa = kid in ALPHA
        if (wu, isa) not in mesh_cache:
            me = baked_cap(wu)
            me.materials.append(cap_mats[0] if isa else cap_mats[1])
            for p in me.polygons:
                p.use_smooth = True
            mesh_cache[(wu, isa)] = me
            tree_cache[(wu, isa)] = BVHTree.FromPolygons([tuple(v.co) for v in me.vertices],
                                                         [tuple(p.vertices) for p in me.polygons])
        o = link(bpy.data.objects.new("Key_" + kid, mesh_cache[(wu, isa)]), kb)
        # slight per-key variation (seat height, tilt, yaw)
        o.location = (x + rng.uniform(-0.015, 0.015), y + rng.uniform(-0.02, 0.02), CAP_Z + rng.uniform(-0.03, 0.02))
        o.rotation_euler = (math.radians(ROW_TILT[r] + rng.uniform(-0.45, 0.45)),
                            math.radians(rng.uniform(-0.5, 0.5)), math.radians(rng.uniform(-0.6, 0.6)))
        key_objs[kid] = o
        parts = legend_parts(kid, wu)
        if parts:
            lm = project_legend(parts, tree_cache[(wu, isa)], "Lg_" + kid)
            lm.materials.append(ink)
            link(bpy.data.objects.new("Legend_" + kid, lm), o)
    key_objs['__stem'] = stem_root
    return kb, key_objs


def animate_keys(key_objs):
    for kid, o in key_objs.items():
        evs = [(t, h) for t, k, h in KEY_EVENTS if k == (HERO_KEY if kid == '__stem' else kid)]
        frames = set()
        for t, h in evs:
            for f in range(int(t) - 1, int(t + 1.6 + h + 7) + 2):
                if 1 <= f <= FRAME_END:
                    frames.add(f)
        x, y, z = o.location
        for f in sorted(frames):
            o.location = (x, y, z - depth(HERO_KEY if kid == '__stem' else kid, f) * KEY_TRAVEL)
            o.keyframe_insert('location', frame=f)


# -------------------------------------------------------------------- MOUSE
MOUSE_L, MOUSE_W, MOUSE_H = 10.4, 5.9, 3.7


def _hump(y):
    return (1 - 0.30 * max(0.0, (y + 0.1) / 1.1) ** 1.7 - 0.14 * max(0.0, (-0.1 - y) / 0.9) ** 2)


def mouse_deform(p):
    x, y, z = p
    x = math.copysign(abs(x) ** 0.82, x)
    z = max(z, 0.0) ** 0.9
    wf = 0.94 - 0.11 * y
    return Vector((x * MOUSE_W / 2 * wf, y * MOUSE_L / 2, z * MOUSE_H * _hump(y)))


def hull_z(y_abs):
    yu = y_abs / (MOUSE_L / 2)
    return MOUSE_H * _hump(yu) * math.sqrt(max(0.0, 1 - yu * yu)) ** 0.9


def shell_mesh(scale=1.0):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=72, v_segments=36, radius=1.0)
    for v in bm.verts:
        v.co = mouse_deform(v.co) * scale
    me = bpy.data.meshes.new("Shell")
    bm.to_mesh(me)
    bm.free()
    return me


def boolean_mesh(src_mesh, ops, name, bevel=0.0):
    ob = link(bpy.data.objects.new("tmp", src_mesh.copy()))
    tmp = []
    for kind, size, centre in ops:
        bo = link(bpy.data.objects.new("opnd", box_mesh("b", size)))
        bo.location = centre
        tmp.append(bo)
        md = ob.modifiers.new("bool", 'BOOLEAN')
        md.operation, md.object, md.solver = kind, bo, 'EXACT'
    if bevel:
        b = ob.modifiers.new("B", 'BEVEL')
        b.width, b.segments, b.limit_method, b.angle_limit = bevel, 2, 'ANGLE', math.radians(40)
    bpy.context.view_layer.update()
    me = baked(ob, name)
    for o in tmp + [ob]:
        bpy.data.objects.remove(o)
    return me


def build_mouse(parent, mats):
    root = empty("Mouse", (52.0, -2.0, 0.35), parent)
    shell = mk("MouseBody", shell_mesh(1.0), mat=mats['body'], parent=root)
    y_s = -1.0
    ycw = 1.8
    big = 20.0
    seam_mat = simple_mat("MouseSeam", "141518", rough=0.5)
    mk("SeamCross", boolean_mesh(shell_mesh(1.02), [("INTERSECT", (30.0, 0.1, 30.0), (0, y_s, 10.0))], "SeamC"),
       mat=seam_mat, parent=root)
    mk("SeamRing", boolean_mesh(shell_mesh(1.019), [("INTERSECT", (30.0, 30.0, 0.07), (0, 0, 1.0))], "SeamR"),
       mat=seam_mat, parent=root)
    mk("Skirt", boolean_mesh(shell_mesh(1.008), [("INTERSECT", (30.0, 30.0, 0.5), (0, 0, 0.25))], "SkirtM"),
       mat=mats['rubber'], parent=root)
    slot = ("DIFFERENCE", (1.1, 12.0, 8.0), (0, y_s + 4.0 + 0.3, 3.0))
    btn_meshes = {}
    for side in (1, -1):
        keep = ("INTERSECT", (big, big, big), (side * (0.06 + big / 2), y_s + big / 2, 1.1 + big / 2))
        btn_meshes[side] = boolean_mesh(shell_mesh(1.014), [keep, slot], f"Btn{side}", bevel=0.05)
    pivot_y = y_s
    pz = hull_z(y_s) * 0.95
    btns = {}
    for side, nm in ((-1, 'L'), (1, 'R')):
        me = btn_meshes[-side if False else side]
        me.transform(Matrix.Translation((0, -pivot_y, -pz)))
        for p in me.polygons:
            p.use_smooth = True
        b = mk("Btn" + nm, me, (0, pivot_y, pz), mats['btn'], root)
        btns[nm] = b
    # wheel (knurled)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=36, radius1=0.95, radius2=0.95, depth=0.62)
    for i, v in enumerate(bm.verts):
        ang = math.atan2(v.co.y, v.co.x)
        k = 1.0 + 0.07 * math.cos(ang * 24)
        v.co.x *= k
        v.co.y *= k
    for v in bm.verts:
        v.co = Vector((v.co.z, v.co.x, v.co.y))        # axis along X
    me = bpy.data.meshes.new("Wheel")
    bm.to_mesh(me)
    bm.free()
    wheel = mk("Wheel", me, (0, ycw, hull_z(ycw) - 0.42), mats['rubber'], root, smooth=False)
    metal = simple_mat("WheelHub", "9A9DA5", rough=0.3, metal=0.9)
    for sx in (-0.33, 0.33):
        bmh = bmesh.new()
        bmesh.ops.create_cone(bmh, cap_ends=True, segments=32, radius1=0.62, radius2=0.62, depth=0.06)
        for v in bmh.verts:
            v.co = Vector((v.co.z, v.co.x, v.co.y))
        meh = bpy.data.meshes.new("Hub")
        bmh.to_mesh(meh)
        bmh.free()
        mk("Hub", meh, (sx, 0, 0), metal, wheel)
    # DPI button + side buttons
    dpi = mk("Dpi", box_mesh("dpi", (0.8, 1.1, 0.5), bevel=0.15, seg=2), (0, -0.05, hull_z(-0.05) - 0.12),
             mats['rubber'], root)
    for i, (yy, nm) in enumerate(((0.9, 'S1'), (-1.5, 'S2'))):
        mk(nm, box_mesh(nm, (0.75, 1.9, 0.95), bevel=0.22, seg=3), (-2.42, yy, 1.45), mats['rubber'], root)
    # RGB light strip around the rear base (follows the same hull deformation)
    bm = bmesh.new()
    rings = []
    for zc in (0.12, 0.5):
        ring = []
        steps = 80
        for i in range(steps + 1):
            a = math.radians(-205 + 230 * i / steps) if False else math.radians(120 + 300 * i / steps)
            xu, yu = math.cos(a), math.sin(a)
            if yu > 0.3:
                continue
            zu = (zc / MOUSE_H) ** (1 / 0.9)
            rr = math.sqrt(max(0.0, 1 - zu * zu))
            p = mouse_deform((xu * rr, yu * rr, zu)) * 1.012
            p.z = zc
            ring.append(bm.verts.new(p))
        rings.append(ring)
    a, b = rings
    for i in range(min(len(a), len(b)) - 1):
        bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
    me = bpy.data.meshes.new("Strip")
    bm.to_mesh(me)
    bm.free()
    sm, snt = new_mat("RGBStrip")
    so = N(snt, 'ShaderNodeOutputMaterial', 300, 0)
    em = N(snt, 'ShaderNodeEmission', 0, 0)
    em.inputs['Strength'].default_value = 7.0
    L(snt, em.outputs['Emission'], so.inputs['Surface'])
    sm.use_backface_culling = False
    strip = mk("RGBStrip", me, (0, 0, 0), sm, root)
    glow_ld = bpy.data.lights.new("MouseGlow", 'POINT')
    glow_ld.energy, glow_ld.shadow_soft_size = 40.0, 1.6
    glow = link(bpy.data.objects.new("MouseGlow", glow_ld), root)
    glow.location = (0, -1.5, 0.9)
    return root, btns, wheel, em, glow_ld


def animate_mouse(root, btns, wheel, em, glow_ld):
    x0, y0, z0 = root.location
    pts = [(1, 0, 0, 0), (18, 2.2, 1.4, 3), (32, 1.0, 3.0, -2), (50, -1.6, 2.2, -4), (66, -1.8, 0.6, -1),
           (84, 0.6, -0.6, 2), (104, 3.0, 0.4, 5), (130, 2.0, -1.2, 1), (170, 1.2, -1.0, 0), (480, 1.2, -1.0, 0)]
    fx = [(p[0], p[1]) for p in pts]
    fy = [(p[0], p[2]) for p in pts]
    fr = [(p[0], p[3]) for p in pts]
    for f in range(1, 260):
        jit = 0.08 * math.sin(f * 0.9) * math.sin(f * 0.23)
        root.location = (x0 + spl(f, fx) + jit, y0 + spl(f, fy) - jit, z0)
        root.rotation_euler = (0, 0, math.radians(spl(f, fr)))
        root.keyframe_insert('location', frame=f)
        root.keyframe_insert('rotation_euler', frame=f)
    clicks = [(40, 2.4), (44, 2.4), (97, 2.6), (129, 2.2), (171, 2.5)]
    for f in range(1, 260):
        ang = 0.0
        for t, h in clicks:
            ang = min(ang, -math.radians(1.6) * press_profile(f - t, h))
        btns['L'].rotation_euler = (ang, 0, 0)
        btns['L'].keyframe_insert('rotation_euler', frame=f)
    for f in range(1, 260):
        wheel.rotation_euler = (math.radians(spl(f, [(1, 0), (66, 0), (82, 150), (96, 330), (120, 360), (480, 360)])),
                                0, 0)
        wheel.keyframe_insert('rotation_euler', frame=f)
    for f in range(1, 481, 3):
        r, g, b = colorsys.hsv_to_rgb((f / 140.0) % 1.0, 0.85, 1.0)
        em.inputs['Color'].default_value = (r ** 2.2, g ** 2.2, b ** 2.2, 1)
        em.inputs['Color'].keyframe_insert('default_value', frame=f)
        glow_ld.color = (r, g, b)
        glow_ld.keyframe_insert('color', frame=f)


# ------------------------------------------------------------------ MONITOR
SW, SH = 85.0, 47.8
CODE_X0 = -SW / 2 + 22.0


def line_y(i):
    return SH / 2 - 7.2 - i * 2.05


def build_monitor(parent):
    body_mat = simple_mat("MonBody", "2B2D32", rough=0.38, metal=0.4)
    mon = empty("Monitor", (0, 55.0, 38.0), parent)
    mon.rotation_euler = (math.radians(-4.0), 0, 0)
    mk("MonBody", box_mesh("MonBody", (SW + 2.0, 2.6, SH + 2.0), bevel=0.35, plan_r=0.8, seg=3,
                           off=(0, 1.3, 0)), mat=body_mat, parent=mon)
    mk("MonBack", box_mesh("MonBack", (SW * 0.6, 3.0, SH * 0.6), bevel=0.8, plan_r=1.5, seg=4,
                           off=(0, 3.8, 0)), mat=body_mat, parent=mon)
    top = empty("Screen", (0, -0.04, 0), mon)
    top.rotation_euler = (math.radians(90), 0, 0)         # local z -> out of the screen
    # world-space neck + base
    mk("Neck", box_mesh("Neck", (6.0, 2.6, 16.0), bevel=0.4), (0, 59.0, 12.0), body_mat, parent)
    mk("Base", box_mesh("Base", (34.0, 20.0, 1.0), bevel=0.35, plan_r=3.0, seg=3), (0, 52.5, 0.5),
       body_mat, parent)
    # screen contents
    bg = mk("ScreenBG", rect_mesh("bg", [(-SW / 2, -SH / 2, SW / 2, SH / 2)]), (0, 0, 0),
            emit_mat("EdBG", "13161C", 1.0), top, smooth=False)
    chrome = [(-SW / 2, SH / 2 - 2.6, SW / 2, SH / 2),                        # title bar
              (-SW / 2, -SH / 2, -SW / 2 + 14.0, SH / 2 - 2.6),               # sidebar
              (-SW / 2 + 14.0, SH / 2 - 5.6, SW / 2, SH / 2 - 2.6),           # tab bar
              (-SW / 2, -SH / 2, SW / 2, -SH / 2 + 1.7)]                      # status bar
    mk("Chrome", rect_mesh("chrome", chrome, 0.03), mat=emit_mat("EdChrome", "1C2028", 1.0), parent=top,
       smooth=False)
    side_items = [(-SW / 2 + 2.0, SH / 2 - 7.0 - i * 2.4, -SW / 2 + 2.0 + w, SH / 2 - 7.0 - i * 2.4 + 0.8)
                  for i, w in enumerate([8, 6, 9, 5, 7, 8, 4, 6, 7])]
    mk("SideItems", rect_mesh("si", side_items, 0.06), mat=emit_mat("EdSide", "4A5160", 1.0), parent=top,
       smooth=False)
    gut = [(CODE_X0 - 6.4, line_y(i) - 0.4, CODE_X0 - 5.0 + (0.5 if i >= 9 else 0), line_y(i) + 0.4)
           for i in range(20)]
    mk("Gutter", rect_mesh("gut", gut, 0.06), mat=emit_mat("EdGut", "3A404C", 1.0), parent=top, smooth=False)
    mk("Tab", rect_mesh("tab", [(-SW / 2 + 16, SH / 2 - 5.0, -SW / 2 + 28, SH / 2 - 3.2),
                                (-SW / 2 + 30, SH / 2 - 5.0, -SW / 2 + 40, SH / 2 - 3.2)], 0.06),
       mat=emit_mat("EdTab", "6B7380", 1.0), parent=top, smooth=False)
    mk("StatusAcc", rect_mesh("sa", [(-SW / 2, -SH / 2, -SW / 2 + 16, -SH / 2 + 1.7)], 0.06),
       mat=emit_mat("EdAcc", "3D7DD8", 1.0), parent=top, smooth=False)
    cols = {"kw": "FF7A59", "id": "D7DAE0", "fn": "61AFEF", "str": "8CD17D", "num": "E5C07B", "cm": "5C6370"}
    mats = {k: emit_mat("Tok_" + k, v, 1.15) for k, v in cols.items()}
    rng = random.Random(5)
    units = {}
    for k in cols:
        um = rect_mesh("tok_" + k, [(0.0, -0.5, 1.0, 0.5)], 0.0)
        um.materials.append(mats[k])
        units[k] = um
    static = []
    for i in range(8):
        x = rng.choice([2.4, 2.4, 4.8, 7.2])
        for k in range(rng.randint(2, 5)):
            w = rng.uniform(2.4, 9.0)
            static.append((i, x, w, rng.choice(list(cols))))
            x += w + 1.2
    n = 0
    for (i, x, w, col) in static:
        o = link(bpy.data.objects.new(f"S{n}", units[col]), top)
        n += 1
        o.location = (CODE_X0 + x, line_y(i), 0.09)
        o.scale = (w, 0.95, 1)
    for tk in TOKENS:
        o = link(bpy.data.objects.new(f"K{n}", units[tk['col']]), top)
        n += 1
        o.location = (CODE_X0 + tk['x0'], line_y(tk['line']), 0.09)
        t = int(tk['t'])
        for f, sx in ((1, 0.0001), (max(1, t - 1), 0.0001), (t + 1, tk['w'])):
            o.scale = (sx, 0.95 if sx > 0.01 else 0.0001, 1)
            o.keyframe_insert('scale', frame=f)
    # caret
    cm = emit_mat("Caret", "F2F4F8", 1.6)
    cme = rect_mesh("caret", [(0.0, -0.55, 0.28, 0.55)], 0.0)
    caret = mk("Caret", cme, (CODE_X0, line_y(8), 0.12), cm, top, smooth=False)
    return mon, top, caret


def animate_caret(caret):
    last = 0.0
    for f in range(1, 252):
        cur = CARET[0]
        for c in CARET:
            if c[0] <= f:
                cur = c
        recent = f - cur[0] < 22 and cur[0] > 0
        vis = 1.0 if recent else (1.0 if (f // 14) % 2 == 0 else 0.0)
        caret.location = (CODE_X0 + cur[1] + 0.3, line_y(cur[2]), 0.12)
        caret.scale = (vis if vis else 0.001, 1, 1)
        caret.keyframe_insert('location', frame=f)
        caret.keyframe_insert('scale', frame=f)


# -------------------------------------------------------------- ROOM + LIGHT
def build_room(parent):
    dmesh = bpy.data.meshes.new("DeskMesh")
    dmesh.from_pydata([(-260, -170, 0), (260, -170, 0), (260, 82, 0), (-260, 82, 0)], [], [(0, 1, 2, 3)])
    mk("Desk", dmesh, mat=desk_material(), parent=parent, smooth=False)
    wmesh = bpy.data.meshes.new("WallMesh")
    wmesh.from_pydata([(-400, 82, 0), (400, 82, 0), (400, 82, 400), (-400, 82, 400)], [], [(0, 1, 2, 3)])
    mk("Wall", wmesh, mat=simple_mat("Wall", WALL_HEX, rough=0.9, bump=0.12, bump_scale=700.0), parent=parent,
       smooth=False)
    mat_m = simple_mat("DeskMat", "2E343C", rough=0.52, bump=0.25, bump_scale=420.0)
    mk("Mat", box_mesh("Mat", (40.0, 34.0, 0.35), bevel=0.12, plan_r=2.5, seg=3, off=(0, 0, 0.175)),
       (52.0, -1.5, 0.0), mat_m, parent)
    build_props(parent)


def lathe(profile, seg=64, name="lathe"):
    """Solid of revolution from (radius, z) points (closed when it starts/ends on the axis)."""
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        rings.append([bm.verts.new((r * math.cos(2 * math.pi * i / seg), r * math.sin(2 * math.pi * i / seg), z))
                      for i in range(seg)])
    for k in range(len(rings) - 1):
        for i in range(seg):
            j = (i + 1) % seg
            try:
                bm.faces.new((rings[k][i], rings[k][j], rings[k + 1][j], rings[k + 1][i]))
            except ValueError:
                pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def tube_mesh(p0, p1, r, name, seg=16):
    d = Vector(p1) - Vector(p0)
    me = lathe([(0, 0), (r, 0), (r, d.length), (0, d.length)], seg, name)
    me.transform(Matrix.Translation(Vector(p0)) @ d.to_track_quat('Z', 'Y').to_matrix().to_4x4())
    return me


def build_props(parent):
    # mug (right of the monitor base, behind the mat)
    mug = [(0, 0.0), (4.6, 0.0), (5.1, 0.5), (5.3, 1.2), (5.5, 12.4), (5.5, 12.9), (5.15, 13.0), (4.9, 12.9),
           (4.8, 3.0), (4.4, 2.5), (0, 2.5)]
    mroot = empty("Mug", (50.0, 34.0, 0.0), parent)
    mroot.rotation_euler = (0, 0, math.radians(35))
    ceramic = simple_mat("Ceramic", "D9D1C0", rough=0.3, coat=0.4)
    mk("MugBody", lathe(mug, 64, "MugM"), mat=ceramic, parent=mroot)
    hm = bpy.data.meshes.new("Handle")
    hb = bmesh.new()
    segs, tseg = 28, 10
    rows = []
    for i in range(segs + 1):
        a = math.radians(-110 + 220 * i / segs)
        c = Vector((5.2 + 3.1 * math.cos(a), 0, 6.6 + 3.9 * math.sin(a)))
        row = []
        for j in range(tseg):
            t = 2 * math.pi * j / tseg
            row.append(hb.verts.new(c + Vector((0.55 * math.cos(t), 0.5 * math.sin(t), 0.55 * math.sin(t)))))
        rows.append(row)
    for k in range(len(rows) - 1):
        for j in range(tseg):
            j2 = (j + 1) % tseg
            hb.faces.new((rows[k][j], rows[k][j2], rows[k + 1][j2], rows[k + 1][j]))
    bmesh.ops.recalc_face_normals(hb, faces=hb.faces[:])
    hb.to_mesh(hm)
    hb.free()
    mk("MugHandle", hm, mat=ceramic, parent=mroot)
    coffee = bpy.data.meshes.new("Coffee")
    coffee.from_pydata([(4.9 * math.cos(2 * math.pi * i / 48), 4.9 * math.sin(2 * math.pi * i / 48), 11.2)
                        for i in range(48)] + [(0, 0, 11.2)], [], [(i, (i + 1) % 48, 48) for i in range(48)])
    mk("Coffee", coffee, mat=simple_mat("Coffee", "1A0F0A", rough=0.12), parent=mroot)

    # potted plant (right, in front of the wall)
    proot = empty("Plant", (74.0, 62.0, 0.0), parent)
    pot = [(0, 0), (4.4, 0), (6.2, 0.4), (7.2, 9.5), (7.6, 10.4), (7.0, 10.6), (6.4, 9.8), (0, 9.4)]
    mk("Pot", lathe(pot, 48, "PotM"), mat=simple_mat("Terracotta", "A8573A", rough=0.75, bump=0.15,
                                                       bump_scale=90), parent=proot)
    mk("Soil", lathe([(0, 9.6), (6.3, 9.7), (0, 9.9)], 24, "SoilM"), mat=simple_mat("Soil", "241A14", rough=0.95),
       parent=proot)
    leaf_mat = simple_mat("Leaf", "3E6B3A", rough=0.5, sheen=0.3)
    rng = random.Random(41)
    for i in range(11):
        ang = i * 2.399 + rng.uniform(-0.2, 0.2)
        ln = rng.uniform(13.0, 21.0)
        tilt = rng.uniform(25.0, 62.0)
        lm = bpy.data.meshes.new("Leaf")
        lb = bmesh.new()
        n = 10
        vs_l, vs_r = [], []
        for k in range(n + 1):
            t = k / n
            w = 3.0 * math.sin(math.pi * min(1.0, t * 1.05)) ** 0.8 * (1 - 0.25 * t)
            z = ln * 0.55 * math.sin(t * 1.5) - 0.18 * ln * t * t
            vs_l.append(lb.verts.new((ln * t, -w, z)))
            vs_r.append(lb.verts.new((ln * t, w, z)))
        for k in range(n):
            lb.faces.new((vs_l[k], vs_l[k + 1], vs_r[k + 1], vs_r[k]))
        lb.to_mesh(lm)
        lb.free()
        for q in lm.polygons:
            q.use_smooth = True
        lo = mk("Leaf", lm, (0, 0, 9.8), leaf_mat, proot)
        lo.rotation_euler = (math.radians(rng.uniform(-14, 14)), math.radians(-(90 - tilt)), ang)

    # desk lamp silhouette (left of the monitor, off axis of the keyboard)
    lroot = empty("Lamp", (-60.0, 62.0, 0.0), parent)
    lamp_mat = simple_mat("LampMetal", "2A2C31", rough=0.38, metal=0.6)
    mk("LampBase", lathe([(0, 0), (8.0, 0), (8.0, 1.0), (7.2, 1.5), (0, 1.5)], 48, "LB"), mat=lamp_mat,
       parent=lroot)
    mk("LampArm1", tube_mesh((0, 0, 1.2), (6.0, 0.0, 30.0), 0.55, "LA1"), mat=lamp_mat, parent=lroot)
    mk("LampArm2", tube_mesh((6.0, 0, 30.0), (-8.0, 0.0, 49.0), 0.5, "LA2"), mat=lamp_mat, parent=lroot)
    sh = lathe([(1.6, 0.0), (1.8, 1.2), (6.5, 9.5), (6.1, 9.7), (1.5, 1.4), (1.4, 0.3)], 48, "LS")
    sh.transform(Matrix.Rotation(math.radians(-62), 4, 'Y'))
    mk("LampShade", sh, (-8.5, 0, 48.3), lamp_mat, lroot)


def build_blinds():
    """Window gobo (frame, mullions, blind slats) upwind of the sun; shadow-only, invisible to the camera."""
    d = SUN_DIR
    target = Vector((8.0, 18.0, 6.0))
    c = target - d * 95.0
    u = d.cross(Vector((0, 0, 1))).normalized()
    v = u.cross(d).normalized()
    bJ = v.dot(JK0 - target)
    bm = bmesh.new()

    def box(a0, a1, b0, b1, th=1.2):
        m = Matrix(((u.x * (a1 - a0) / 2, v.x * (b1 - b0) / 2, d.x * th, 0),
                    (u.y * (a1 - a0) / 2, v.y * (b1 - b0) / 2, d.y * th, 0),
                    (u.z * (a1 - a0) / 2, v.z * (b1 - b0) / 2, d.z * th, 0),
                    (0, 0, 0, 1)))
        m.translation = c + u * (a0 + a1) / 2 + v * (b0 + b1) / 2
        bmesh.ops.create_cube(bm, size=2.0, matrix=m)

    A0, A1, B0, B1 = -104.0, 104.0, -46.0, 86.0
    for rect in ((-600, A0, -600, 600), (A1, 600, -600, 600), (A0, A1, -600, B0), (A0, A1, B1, 600)):
        box(*rect)
    for am in (-46.0, 41.0):                          # mullions
        box(am - 3.0, am + 3.0, B0, B1)
    box(A0, A1, 52.0, 57.0)                           # transom
    b = bJ + 6.5 - 12.0 * 4
    while b < B1:                                     # blind slats, 12 pitch / 5 wide
        lo, hi = max(b, B0), min(b + 3.6, B1)
        if hi > lo:
            box(A0, A1, lo, hi)
        b += 12.0
    me = bpy.data.meshes.new("BlindsM")
    bm.to_mesh(me)
    bm.free()
    ob = mk("Blinds", me, mat=simple_mat("Blk", "050505"), smooth=False)
    ob.visible_camera = False
    return ob


def add_light(name, kind, loc, energy, color=(1, 1, 1), target=None, size=6.0, size_y=None, parent=None):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color
    if kind == 'AREA':
        ld.shape = 'RECTANGLE' if size_y else 'SQUARE'
        ld.size = size
        if size_y:
            ld.size_y = size_y
    ob = link(bpy.data.objects.new(name, ld), parent)
    ob.location = loc
    if target is not None:
        c = ob.constraints.new('TRACK_TO')
        c.target = target
        c.track_axis = 'TRACK_NEGATIVE_Z'
        c.up_axis = 'UP_Y'
    return ob, ld


def build_world():
    w = bpy.data.worlds.new("World")
    scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = N(nt, 'ShaderNodeOutputWorld', 600, 0)
    lp = N(nt, 'ShaderNodeLightPath', 0, 200)
    light = N(nt, 'ShaderNodeBackground', 200, 0)
    light.inputs['Color'].default_value = lin4("A9BEDD")
    cam_bg = N(nt, 'ShaderNodeBackground', 200, -200)
    cam_bg.inputs['Color'].default_value = lin4(WALL_HEX)
    mix = N(nt, 'ShaderNodeMixShader', 400, 0)
    L(nt, lp.outputs['Is Camera Ray'], mix.inputs[0])
    L(nt, light.outputs[0], mix.inputs[1])
    L(nt, cam_bg.outputs[0], mix.inputs[2])
    L(nt, mix.outputs[0], out.inputs['Surface'])
    return light, cam_bg


def set_keys(target, prop, pairs, index=-1):
    for f, v in pairs:
        if index >= 0:
            getattr(target, prop)[index] = v
        else:
            setattr(target, prop, v)
        target.keyframe_insert(prop, frame=f, index=index) if index >= 0 else target.keyframe_insert(prop, frame=f)


# ------------------------------------------------------------------- BUILD
def dirv(az, el):
    a, e = math.radians(az), math.radians(el)
    return Vector((math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)))


def cam_quat(d):
    return (-d).to_track_quat('-Z', 'Y')


TOP_LOCAL = CAP_H / 2 - CAP_DISH
H_DIR = dirv(-94, 44)
HERO_H = JK0 + H_DIR * 9.0 + Vector((0, 0, 6.0))
# scalar camera waypoints: frame, az, el, dist, lens, fstop (BU-as-metres: tiny numbers, see notes)
CAM_WP = None            # filled in build() once d_final is known


def hero_follow(f):
    """0..1 progress of the key along its flight."""
    return ease((f - POP_FRAME) / 35.0)


def hero_pos(f):
    if f <= POP_FRAME:
        local = HERO_LOCAL.copy()
        d = depth(HERO_KEY, f) * KEY_TRAVEL
        if f > 211.0:
            d = max(0.0, d)
        local.translation = local.translation + Vector((0, 0, -d))
        return (KB_M @ local).translation
    u = hero_follow(f)
    n = (KB_M.to_quaternion() @ Vector((0, 0, 1)))
    p0, p3 = JK0, HERO_H
    p1 = p0 + n * 12.0
    p2 = p3 - H_DIR * 3.0 + Vector((0, 0, 5.0))
    p = (p0 * (1 - u) ** 3 + p1 * 3 * u * (1 - u) ** 2 + p2 * 3 * u * u * (1 - u) + p3 * u ** 3)
    p += n * (2.6 * math.sin(math.pi * min(1.0, (f - POP_FRAME) / 11.0)))
    if f > 250:
        p += Vector((0, 0, 0.25 * math.sin((f - 250) / 26.0) * ease((f - 250) / 25.0)))
    return p


def cam_state(f):
    az, el, dist, lens, fs = (spl(f, [(w[0], w[k]) for w in CAM_WP]) for k in range(1, 6))
    ws = [(1, Vector((16, 24, 27))), (120, Vector((10, 12, 14))), (160, Vector((1.0, -1.0, 3.0))),
          (200, JK0 + Vector((-1.0, 0.2, 0.0))), (POP_FRAME, JK0 + Vector((0, 0, 0.3)))]
    if f <= POP_FRAME:
        T = spl(f, ws)
    else:
        T0 = spl(POP_FRAME, ws)
        acc, cnt = Vector((0, 0, 0)), 0
        for k in range(-3, 4):
            acc += hero_pos(max(POP_FRAME + 0.01, f + k))
            cnt += 1
        w = ease((f - POP_FRAME) / 4.0)
        T = T0 * (1 - w) + (acc / cnt) * w
        T += dirv(az, el) * (TOP_LOCAL * ease((f - 401) / 79.0))
    return T, az, el, dist, lens, fs


def hero_quats():
    qB = cam_quat(dirv(*cam_ae(365))) @ Quaternion((1, 0, 0), math.radians(-40)) @ Quaternion((0, 1, 0), math.radians(26))
    qB2 = cam_quat(dirv(*cam_ae(400))) @ Quaternion((1, 0, 0), math.radians(-28)) @ Quaternion((0, 1, 0), math.radians(-20))
    return qB, qB2


def cam_ae(f):
    return (spl(f, [(w[0], w[1]) for w in CAM_WP]), spl(f, [(w[0], w[2]) for w in CAM_WP]))


def hero_quat(f, qB, qB2):
    if f <= POP_FRAME:
        return Q_KB.copy()
    base = Q_KB.slerp(qB, ease((f - POP_FRAME) / (330 - POP_FRAME)))
    if f > 330:
        base = qB.slerp(qB2, ease((f - 330) / 70.0))
    if f > 401:
        qc = cam_quat(dirv(*cam_ae(f)))
        if qB2.dot(qc) < 0:
            qc.negate()
        base = qB2.slerp(qc, ease((f - 401) / 39.0))
    s = max(0.0, min(1.0, (f - POP_FRAME) / (330 - POP_FRAME)))
    s2 = max(0.0, min(1.0, (f - POP_FRAME - 5) / (330 - POP_FRAME - 5)))
    a1 = 2 * math.pi * 2.0 * (1 - (1 - s) ** 3)
    a2 = 2 * math.pi * 1.0 * (1 - (1 - s2) ** 3)
    r1 = Quaternion(Vector((0.3, 1.0, 0.2)).normalized(), a1)
    r2 = Quaternion(Vector((1.0, 0.15, 0.5)).normalized(), a2)
    return r1 @ r2 @ base


def build():
    global CAM_WP
    clear_scene()
    scene.frame_start, scene.frame_end = 1, FRAME_END
    scene.render.fps = FPS
    scene.render.resolution_percentage = 100
    try:
        bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    except Exception:
        pass
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.display_settings.display_device = 'sRGB'
    scene.render.dither_intensity = 0.0
    scene.render.film_transparent = False

    # hero keycap (vermilion, dished, engraved legend)
    cap_mat, gloss, ripple_amt, wave = keycap_material()
    hero = link(bpy.data.objects.new("Keycap", build_keycap_mesh(1.0)))
    for p in hero.data.polygons:
        p.use_smooth = True
    hero.data.materials.append(cap_mat)
    z0 = CAP_H / 2 - CAP_DISH
    cut_me, txt_h = text_mesh(0.1, "Cutter")
    fill_me, _ = text_mesh(0.0175, "Filler")
    cutter = link(bpy.data.objects.new("LegendCutter", cut_me), hero)
    cutter.location = (0, 0, z0 - ENGRAVE_DEPTH + 0.1)
    cutter.display_type = 'WIRE'
    cutter.hide_render = True
    filler = link(bpy.data.objects.new("Legend", fill_me), hero)
    filler.location = (0, 0, z0 - 0.0375)
    fill_me.materials.append(legend_material())
    bev = hero.modifiers.new("Bevel", 'BEVEL')
    bev.width, bev.segments = 0.16, 6
    bev.limit_method, bev.angle_limit = 'ANGLE', math.radians(35)
    sub = hero.modifiers.new("Subsurf", 'SUBSURF')
    sub.levels = sub.render_levels = 2
    boo = hero.modifiers.new("Engrave", 'BOOLEAN')
    boo.operation, boo.operand_type, boo.object, boo.solver = 'DIFFERENCE', 'OBJECT', cutter, 'EXACT'
    hero.rotation_mode = 'QUATERNION'
    # bake the engraved cap once; crisp walls = sharp edges, everything else smooth
    bpy.context.view_layer.update()
    hm = baked(hero, "KeycapBaked")
    hero.modifiers.clear()
    hero.data = hm
    bpy.data.objects.remove(cutter)
    hb = bmesh.new()
    hb.from_mesh(hm)
    for f_ in hb.faces:
        f_.smooth = True
    for e_ in hb.edges:
        if len(e_.link_faces) == 2 and e_.calc_face_angle(0.0) > math.radians(38):
            e_.smooth = False
    hb.to_mesh(hm)
    hb.free()

    # workspace
    ws = empty("Workspace")
    build_room(ws)
    cap_mats = (board_cap_material("Bone", BONE_HEX), board_cap_material("Mod", MOD_HEX))
    kb, key_objs = build_keyboard(ws, cap_mats)
    animate_keys(key_objs)
    mats = dict(body=simple_mat("MouseBody", "C9C6BF", rough=0.4, coat=0.2),
                btn=simple_mat("MouseBtn", "EFECE5", rough=0.32, coat=0.35),
                rubber=simple_mat("Rubber", "26282C", rough=0.7))
    mroot, btns, wheel, em, glow_ld = build_mouse(ws, mats)
    animate_mouse(mroot, btns, wheel, em, glow_ld)
    mon, top, caret = build_monitor(ws)
    animate_caret(caret)

    bg_light, bg_cam = build_world()

    # camera
    aspect = FINAL_RES[1] / FINAL_RES[0]
    tan_half_v = (CAM_SENSOR_W * aspect / 2) / 85.0
    d_final = txt_h / (LEGEND_FILL * 2 * tan_half_v)
    CAM_WP = [
        (1, -114, 22, 205, 50, 0.0165),
        (120, -106, 28, 160, 50, 0.0185),
        (160, -97, 52, 98, 55, 0.0240),
        (200, -94, 50, 40, 70, 0.075),
        (213, -94, 44, 27, 85, 0.30),
        (232, -94, 36, 32, 85, 0.6),
        (250, -98, 28, 28, 85, 0.5),
        (290, -92, 22, 28, 85, 0.40),
        (330, -86, 21, 27, 85, 0.40),
        (365, -90, 20, 26, 85, 0.40),
        (400, -90, 20, 24, 85, 0.40),
        (440, -90, 10, 14, 85, 0.5),
        (480, -90, 4, d_final, 85, 0.6),
    ]
    cd = bpy.data.cameras.new("Cam")
    cd.sensor_width = CAM_SENSOR_W
    cd.clip_start, cd.clip_end = 0.5, 4000.0
    cam = link(bpy.data.objects.new("Camera", cd))
    cam.rotation_mode = 'QUATERNION'
    scene.camera = cam
    cd.dof.use_dof = True

    KBC = KB_M @ Vector((0, 0, CAP_Z))
    qB, qB2 = hero_quats()
    prev = None
    for f in range(1, FRAME_END + 1):
        hero.location = hero_pos(f)
        q = hero_quat(f, qB, qB2)
        if prev is not None and q.dot(prev) < 0:
            q.negate()
        prev = q
        hero.rotation_quaternion = q
        hero.keyframe_insert('location', frame=f)
        hero.keyframe_insert('rotation_quaternion', frame=f)
        T, az, el, dist, lens, fs = cam_state(f)
        pos = T + dirv(az, el) * dist
        cam.location = pos
        cam.rotation_quaternion = cam_quat(dirv(az, el))
        cd.lens = lens
        if f < 200:
            # rack focus: keyboard first, then pulled onto the JK key by frame 200
            fp = KBC.lerp(JK0, ease((f - 60.0) / 140.0))
            cd.dof.focus_distance = (pos - fp).length
        else:
            cd.dof.focus_distance = dist
        cd.dof.aperture_fstop = fs
        cam.keyframe_insert('location', frame=f)
        cam.keyframe_insert('rotation_quaternion', frame=f)
        cd.keyframe_insert('lens', frame=f)
        cd.dof.keyframe_insert('focus_distance', frame=f)
        cd.dof.keyframe_insert('aperture_fstop', frame=f)

    # workspace falls away during the launch
    for f in [1, 213] + list(range(214, 252, 2)):
        s_ = max(0.0, f - 213.0)
        ws.location = (0, 0, -min(4000.0, 9.0 * s_ * s_))
        ws.keyframe_insert('location', frame=f)

    # ---- lights: low warm window sun through a gobo, cool dim fill, monitor glow
    sun_obj, sun = add_light("Sun", 'SUN', (0, 0, 50), SUN_ENERGY, color=(1.0, 0.80, 0.58))
    sun.angle = math.radians(1.6)
    sun_obj.rotation_mode = 'QUATERNION'
    sun_obj.rotation_quaternion = SUN_DIR.to_track_quat('-Z', 'Y')
    blinds = build_blinds()
    scr_tgt = empty("ScreenTarget", (0, 4.0, 3.0))
    glow_ob, glow = add_light("ScreenGlow", 'AREA', (0, 51.5, 40.0), 24000.0, (0.52, 0.70, 1.0), scr_tgt, 66.0, 34.0,
                              parent=ws)
    fill_tgt = empty("FillTarget", (10.0, 8.0, 8.0))
    fill_ob, fillw = add_light("RoomFill", 'AREA', (70.0, -120.0, 85.0), 9500.0, (0.66, 0.78, 1.0), fill_tgt, 70.0)

    target = hero
    strip_a, sa = add_light("StripA", 'AREA', HERO_H + Vector((-19, 7, 3)), 0.0, (1.0, 0.95, 0.9), target,
                            3.0, 26.0)
    strip_b, sb = add_light("StripB", 'AREA', HERO_H + Vector((19, 7, 3)), 0.0, (0.85, 0.92, 1.0), target,
                            3.0, 26.0)
    fill_o, sf = add_light("StudioFill", 'AREA', HERO_H + Vector((0, -30, 16)), 0.0, (1, 0.97, 0.95), target, 14.0)
    for ld in (sa, sb, sf, sun, fillw, glow):
        ld.use_shadow = True

    def fall(f, a=207.0, b=228.0, pw=2.6):
        """1 -> 0 along a smooth curve between frames a and b."""
        return (1.0 - ease((f - a) / (b - a))) ** pw

    # room lights fall off smoothly 205 -> 240 (no abrupt grey phase)
    base = {sun: SUN_ENERGY, glow: 24000.0, fillw: 9500.0}
    for ld, e0 in base.items():
        for f in [1] + list(range(205, 246)) + [480]:
            ld.energy = e0 * (fall(f) if f >= 205 else 1.0) if f < 480 else 0.0
            ld.keyframe_insert('energy', frame=f)
    # rim lights (kept lit on the key) ramp in as the room falls away
    ENG = dict(A=9000.0, B=8000.0, F=2800.0)
    for ld, e in ((sa, ENG['A']), (sb, ENG['B']), (sf, ENG['F'])):
        keys = [(1, 0.0), (205, 0.0)] + [(f, e * ease((f - 205) / 32.0)) for f in range(206, 238)]
        keys += [(400, e), (450, e * (2.8 if ld is sf else 1.0)), (480, e * (2.8 if ld is sf else 1.0))]
        for f, v in keys:
            ld.energy = v
            ld.keyframe_insert('energy', frame=f)
    # blinds gobo only matters while the sun is up
    for f, hide in ((1, False), (241, True)):
        blinds.hide_render = hide
        blinds.keyframe_insert('hide_render', frame=f)
    # world: dim cool fill -> 0 ; camera-ray background -> exactly BLACK_HEX by 235
    wl = lin4(WALL_HEX)
    bl = lin4(BLACK_HEX)
    for f in [1] + list(range(205, 246)) + [480]:
        w_ = fall(f, 207.0, 226.0, 2.4) if f < 480 else 0.0
        bg_light.inputs['Strength'].default_value = 0.10 * w_
        bg_light.inputs['Strength'].keyframe_insert('default_value', frame=f)
        m_ = fall(f, 209.0, 222.0, 2.4) if f < 480 else 0.0
        bg_cam.inputs['Color'].default_value = tuple(bl[i] + (wl[i] * 0.22 - bl[i]) * m_ for i in range(3)) + (1.0,)
        bg_cam.inputs['Color'].keyframe_insert('default_value', frame=f)
    # glossy top + ripples
    for f, v in ((1, 0.0), (240, 0.0), (290, 1.0), (480, 1.0)):
        gloss.outputs[0].default_value = v
        gloss.outputs[0].keyframe_insert('default_value', frame=f)
    for f, v in ((1, 0.0), (331, 0.0), (345, 1.0), (392, 1.0), (430, 0.0), (480, 0.0)):
        ripple_amt.outputs[0].default_value = v
        ripple_amt.outputs[0].keyframe_insert('default_value', frame=f)
    for f, v in ((331, 0.0), (400, -16.0)):
        wave.inputs['Phase Offset'].default_value = v
        wave.inputs['Phase Offset'].keyframe_insert('default_value', frame=f)
    # motion blur only where it is wanted
    try:
        scene.render.use_motion_blur = True
        for f, v in ((1, 0.10), (205, 0.12), (211, 0.17), (232, 0.20), (250, 0.18), (330, 0.14), (345, 0.08), (480, 0.06)):
            scene.render.motion_blur_shutter = v
            scene.render.keyframe_insert('motion_blur_shutter', frame=f)
    except Exception as e:
        print("motion blur setup:", e)
    scene.frame_set(1)


# ---------------------------------------------------------------- RENDERING
def setup_gpu():
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
    except Exception:
        return False
    for kind in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
        except Exception:
            continue
        gpus = [d for d in prefs.devices if d.type != 'CPU']
        if gpus:
            for d in prefs.devices:
                d.use = d.type != 'CPU'
            return True
    return False


def configure_render(mode, root, out_dir=None):
    res, samples = (PREVIEW_RES, PREVIEW_SAMPLES) if mode == 'preview' else (FINAL_RES, FINAL_SAMPLES)
    scene.render.resolution_x, scene.render.resolution_y = res
    if mode == 'final':
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = samples
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = 'OPENIMAGEDENOISE'
        scene.cycles.max_bounces = 6
        scene.cycles.device = 'GPU' if setup_gpu() else 'CPU'
    else:
        for eng in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
            try:
                scene.render.engine = eng
                break
            except TypeError:
                continue
        ev = scene.eevee
        ev.taa_render_samples = samples
        for attr, val in (('use_raytracing', True), ('use_shadows', True), ('shadow_ray_count', 2),
                          ('shadow_step_count', 8), ('use_fast_gi', True), ('motion_blur_steps', 8)):
            try:
                setattr(ev, attr, val)
            except Exception:
                pass
    im = scene.render.image_settings
    im.file_format = 'WEBP'
    im.color_mode = 'RGB'
    im.quality = WEBP_QUALITY
    out = Path(out_dir) if out_dir else root / "public" / "film" / "desktop"
    out.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(out / "f_####")
    scene.render.use_file_extension = True
    return out


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    mode = 'final' if '--final' in argv else (
        'preview' if ('--preview' in argv or '--frames' in argv or '--list' in argv) else None)
    build()
    if mode is None:
        return
    root = Path(__file__).resolve().parent.parent
    out_dir = argv[argv.index('--out') + 1] if '--out' in argv else None
    out = configure_render(mode, root, out_dir)
    if '--pct' in argv:
        scene.render.resolution_percentage = int(argv[argv.index('--pct') + 1])
    print('RENDER ENGINE/DEVICE:', scene.render.engine, getattr(scene.cycles, 'device', '-'))
    if '--list' in argv:
        for f in [int(x) for x in argv[argv.index('--list') + 1].split(',')]:
            scene.frame_set(f)
            scene.render.filepath = str(out / f"f_{f:04d}")
            bpy.ops.render.render(write_still=True)
        return
    start, end = 1, FRAME_END
    if '--frames' in argv:
        i = argv.index('--frames')
        start, end = int(argv[i + 1]), int(argv[i + 2])
    scene.frame_start, scene.frame_end = start, end
    bpy.ops.render.render(animation=True)


main()
