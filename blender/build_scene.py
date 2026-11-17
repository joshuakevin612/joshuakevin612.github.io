"""Scroll-scrubbed hero film (Blender 5.x): one-shot procedural workspace -> JK keycap.

Preview : blender -b -P blender/build_scene.py -- --preview
Final   : blender -b -P blender/build_scene.py -- --final
Subset  : append  --frames START END     or   --list 1,60,160   (single stills)
Output  : --out DIR  (default public/film/desktop/f_0001.webp ...)

World units: 1 unit ~ 0.6 cm (a 1u key pitch is 3.2 units). Z up, camera starts at -Y.
Beats: 1-120 workspace (static wide to 100, then moves) | 121-200 to keyboard | 201-250 launch | 251-330 spin |
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
FINAL_RES, FINAL_SAMPLES = (1920, 1080), 128        # Cycles, adaptive, OIDN denoise, indirect clamp
WEBP_QUALITY = 85
ACCENT_HEX = KEY_HEX                                 # hardware glow = the site's vermilion
SKY_ENERGY, FILL_ENERGY, FILL_NIGHT = 36000.0, 6500.0, 1100.0
SCREEN_ENERGY, BAR_ENERGY, KBKEY_ENERGY, HERO_ENERGY = 9000.0, 14000.0, 9000.0, 5200.0

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
# Window in the back wall (x0, x1, z0, z1). Time of day: 1-12 morning, 12-80 sunset -> night, 80+ night; camera static until 100.
WIN = (-135.0, -45.0, 30.0, 120.0)
HAZE_DAY, HAZE_NIGHT = 0.0075, 0.0013               # volume density (per world unit)
SUN_HEADING = Vector((0.50, -0.87)).normalized()      # horizontal travel of window sunlight (into the room)
# -------------------------------------------------------------------------

scene = bpy.context.scene
GLOW = []          # (socket, base strength): all hardware emission, keyed by gmul() in finish_glow()


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


def fall(f, a=207.0, b=228.0, pw=2.6):
    """1 -> 0 along a smooth curve between frames a and b."""
    return (1.0 - ease((f - a) / (b - a))) ** pw


def pwl(f, rows, k):
    """Piecewise-linear lookup of column k (float or tuple) in rows of (frame, ...)."""
    if f <= rows[0][0]:
        return rows[0][k]
    for a, b in zip(rows, rows[1:]):
        if f <= b[0]:
            t = (f - a[0]) / (b[0] - a[0])
            if isinstance(a[k], tuple):
                return tuple(x + (y - x) * t for x, y in zip(a[k], b[k]))
            return a[k] + (b[k] - a[k]) * t
    return rows[-1][k]


# ---- time of day (frames): morning hold 1-12, sunset 12-80, full night 80+ (camera static until CAM_START)
SUNSET_A, SUNSET_B, CAM_START = 12.0, 80.0, 100.0


def night(f):
    return ease((f - SUNSET_A) / (SUNSET_B - SUNSET_A))


def sunvis(f):
    return 1.0 - ease((f - 10.0) / 48.0)


def gmul(f):
    """Hardware glow multiplier: subdued in daylight, full at night, gone with the room (205-228)."""
    return (0.08 + 0.92 * night(f) ** 0.8) * (fall(f) if f >= 205 else 1.0)


# ---- RGB: one travelling hue wave drives every emitter (shader side) and every spill light (python side)
HUE_P = 84.0                                   # frames per full trip round the hue wheel
HUE_K = Vector((0.0030, 0.0008, 0.0070))       # hue turns per world unit (x: across the rig, z: up the tower)
_WH = ["FF3040", "FFA21F", "3DDC5A", "1FD0E8", "3A62FF", "B43CFF", "FF3C9A", "FF3040"]
WHEEL_RGB = [hex_lin(h) for h in _WH]


def hue_rgb(h):
    """Linear RGB on the hue wheel, h in turns (same table as the shader colour ramp)."""
    h %= 1.0
    n = len(WHEEL_RGB) - 1
    x = h * n
    i = min(int(x), n - 1)
    t = x - i
    a, b = WHEEL_RGB[i], WHEEL_RGB[i + 1]
    return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))


def hue_at(f, pos):
    return f / HUE_P - (HUE_K.x * pos.x + HUE_K.y * pos.y + HUE_K.z * pos.z)


#            frame, horizon, zenith, strength           (linear RGB)
SKY_ROWS = [(1, (0.95, 0.88, 0.76), (0.30, 0.55, 1.0), 1.0),
            (12, (0.95, 0.88, 0.76), (0.30, 0.55, 1.0), 1.0),
            (32, (1.0, 0.50, 0.16), (0.30, 0.32, 0.62), 0.9),
            (47, (0.80, 0.20, 0.10), (0.07, 0.09, 0.30), 0.7),
            (62, (0.09, 0.06, 0.17), (0.008, 0.02, 0.10), 0.55),
            (80, (0.010, 0.016, 0.045), (0.002, 0.004, 0.016), 0.5)]
#              frame, colour, relative energy
SKYL_ROWS = [(1, (0.96, 0.94, 0.90), 1.0), (12, (0.96, 0.94, 0.90), 1.0),
             (32, (1.0, 0.62, 0.36), 0.65), (47, (0.9, 0.35, 0.28), 0.30),
             (62, (0.25, 0.32, 0.95), 0.10), (80, (0.10, 0.20, 0.95), 0.06)]
WORLD_ROWS = [(1, (0.80, 0.82, 0.88), 0.55), (12, (0.80, 0.82, 0.88), 0.55),
              (32, (0.95, 0.60, 0.40), 0.30), (47, (0.70, 0.30, 0.30), 0.14),
              (62, (0.15, 0.20, 0.60), 0.06), (80, (0.08, 0.14, 0.70), 0.06)]
SUN_ROWS = [(1, (1.0, 0.80, 0.58), 30.0), (12, (1.0, 0.78, 0.55), 28.0), (32, (1.0, 0.55, 0.25), 12.0),
            (47, (1.0, 0.38, 0.15), 4.0), (60, (1.0, 0.30, 0.12), 0.5)]


def sun_dir(f):
    el = math.radians(pwl(f, SUN_ROWS, 2))
    return Vector((SUN_HEADING.x * math.cos(el), SUN_HEADING.y * math.cos(el), -math.sin(el)))


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


HUE_NODES = []      # (Value node) hue time, keyed once the scene is built


def rgb_node(nt, x=-900, y=-400):
    """Colour output that follows the world-space hue wave: hue = frame/HUE_P - dot(HUE_K, position)."""
    gp = N(nt, 'ShaderNodeNewGeometry', x, y)
    dt = N(nt, 'ShaderNodeVectorMath', x + 200, y, operation='DOT_PRODUCT')
    dt.inputs[1].default_value = tuple(HUE_K)
    L(nt, gp.outputs['Position'], dt.inputs[0])
    tv = N(nt, 'ShaderNodeValue', x + 200, y - 200)
    HUE_NODES.append(tv)
    sb = N(nt, 'ShaderNodeMath', x + 400, y, operation='SUBTRACT')
    L(nt, tv.outputs[0], sb.inputs[0])
    L(nt, dt.outputs['Value'], sb.inputs[1])
    fr = N(nt, 'ShaderNodeMath', x + 550, y, operation='FRACT')
    L(nt, sb.outputs[0], fr.inputs[0])
    cr = N(nt, 'ShaderNodeValToRGB', x + 700, y)
    ramp = cr.color_ramp
    ramp.interpolation = 'LINEAR'
    n = len(WHEEL_RGB) - 1
    while len(ramp.elements) < n + 1:
        ramp.elements.new(0.5)
    for i, el in enumerate(ramp.elements):
        el.position = i / n
        el.color = (*WHEEL_RGB[i], 1.0)
    L(nt, fr.outputs[0], cr.inputs['Fac'])
    return cr.outputs['Color']


def glow_mat(name, strength, hexc=ACCENT_HEX, rgb=None, wave=False):
    """Hardware emission: strength is the night value, keyed with gmul(). wave=True follows the RGB wheel."""
    m, nt = new_mat(name)
    out = N(nt, 'ShaderNodeOutputMaterial', 300, 0)
    e = N(nt, 'ShaderNodeEmission', 0, 0)
    e.inputs['Color'].default_value = (*rgb, 1.0) if rgb else lin4(hexc)
    if wave:
        L(nt, rgb_node(nt), e.inputs['Color'])
    e.inputs['Strength'].default_value = strength
    GLOW.append((e.inputs['Strength'], strength))
    L(nt, e.outputs['Emission'], out.inputs['Surface'])
    return m


def glossy_glass(name):
    """Tempered glass without refraction: transparent + a faint fresnel reflection (shadow-free, fast)."""
    m, nt = new_mat(name)
    out = N(nt, 'ShaderNodeOutputMaterial', 600, 0)
    tr = N(nt, 'ShaderNodeBsdfTransparent', 100, 100)
    gl = N(nt, 'ShaderNodeBsdfGlossy', 100, -100)
    gl.inputs['Roughness'].default_value = 0.03
    fr = N(nt, 'ShaderNodeFresnel', 100, 250)
    fr.inputs['IOR'].default_value = 1.5
    fs = N(nt, 'ShaderNodeMath', 250, 250, operation='MULTIPLY')      # keep the reflection faint
    fs.inputs[1].default_value = 0.5
    L(nt, fr.outputs[0], fs.inputs[0])
    mix = N(nt, 'ShaderNodeMixShader', 350, 0)
    L(nt, fs.outputs[0], mix.inputs[0])
    L(nt, tr.outputs[0], mix.inputs[1])
    L(nt, gl.outputs[0], mix.inputs[2])
    L(nt, mix.outputs[0], out.inputs['Surface'])
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
    """Printed legend that is also backlit: vermilion emission, keyed with the hardware glow."""
    m = simple_mat("Ink", INK_HEX, rough=0.42)
    b = [n for n in m.node_tree.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled'][0]
    b.inputs['Emission Color'].default_value = lin4(ACCENT_HEX)
    L(m.node_tree, rgb_node(m.node_tree), b.inputs['Emission Color'])
    b.inputs['Emission Strength'].default_value = 5.0
    GLOW.append((b.inputs['Emission Strength'], 5.0))
    return m


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
    pb = [n for n in plate_mat.node_tree.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled'][0]
    pb.inputs['Emission Color'].default_value = lin4(ACCENT_HEX)    # backlight bleeding between the caps
    L(plate_mat.node_tree, rgb_node(plate_mat.node_tree), pb.inputs['Emission Color'])
    pb.inputs['Emission Strength'].default_value = 0.3
    GLOW.append((pb.inputs['Emission Strength'], 0.3))
    mk("Underglow", box_mesh("Underglow", (KB_W - 9.0, 0.3, 0.55), bevel=0.1, seg=2, off=(0, 0, 0)),
       (0, -KB_D / 2 - 0.02, 1.0), glow_mat("KbUnder", 3.4, wave=True), kb)
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
    em.inputs['Color'].default_value = lin4(ACCENT_HEX)
    em.inputs['Strength'].default_value = 4.0
    GLOW.append((em.inputs['Strength'], 4.0))
    L(snt, rgb_node(snt), em.inputs['Color'])
    L(snt, em.outputs['Emission'], so.inputs['Surface'])
    sm.use_backface_culling = False
    strip = mk("RGBStrip", me, (0, 0, 0), sm, root)
    glow_ld = bpy.data.lights.new("MouseGlow", 'POINT')
    glow_ld.energy, glow_ld.shadow_soft_size = 40.0, 1.6
    glow_ld.color = hex_lin(ACCENT_HEX)
    glow = link(bpy.data.objects.new("MouseGlow", glow_ld), root)
    glow.location = (0, -1.5, 0.9)
    glow.visible_camera = False
    HW_LIGHTS.append((glow_ld, 160.0, glow))
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
    # light bar on top: warm lens on its front face (the matching area light is in build())
    bar_z = SH / 2 + 1.0
    mk("BarBody", box_mesh("BarBody", (34.0, 3.4, 1.7), bevel=0.35, seg=3, off=(0, 0.1, bar_z + 0.8)),
       mat=simple_mat("BarBody", "1B1D21", rough=0.35, metal=0.5), parent=mon)
    mk("BarLens", box_mesh("BarLens", (31.0, 0.3, 0.8), bevel=0.06, seg=2, off=(0, -1.62, bar_z + 0.75)),
       mat=glow_mat("BarLens", 3.0, hexc="FF9A55"), parent=mon)
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
    build_room_shell(parent)


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
    mroot = empty("Mug", (38.0, 36.0, 0.0), parent)
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
    proot = empty("Plant", (-150.0, 66.0, 0.0), parent)
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


# ------------------------------------------------------- WINDOW, MAT, HARDWARE
HW_LIGHTS = []         # (light data, base energy): hardware glow lights, keyed with gmul()
SPINNERS = []          # (rotor empty, turns over frames 1-250)
SKY = {}               # keyable sky sockets


def topo_mat():
    """Dark desk mat with fine, low-contrast topographic contour lines (faint vermilion at night)."""
    m, nt = new_mat("TopoMat")
    out = N(nt, 'ShaderNodeOutputMaterial', 1100, 0)
    b = N(nt, 'ShaderNodeBsdfPrincipled', 800, 0)
    b.inputs['Roughness'].default_value = 0.62
    b.inputs['Sheen Weight'].default_value = 0.3
    tc = N(nt, 'ShaderNodeTexCoord', -900, 0)
    nz = N(nt, 'ShaderNodeTexNoise', -700, 0)
    nz.inputs['Scale'].default_value = 0.034
    nz.inputs['Detail'].default_value = 3.0
    nz.inputs['Roughness'].default_value = 0.55
    nz.inputs['Distortion'].default_value = 0.4
    L(nt, tc.outputs['Object'], nz.inputs['Vector'])
    mul = N(nt, 'ShaderNodeMath', -500, 0, operation='MULTIPLY')
    mul.inputs[1].default_value = 17.0
    L(nt, nz.outputs['Fac'], mul.inputs[0])
    fr = N(nt, 'ShaderNodeMath', -350, 0, operation='FRACT')
    L(nt, mul.outputs[0], fr.inputs[0])
    sb = N(nt, 'ShaderNodeMath', -200, 0, operation='SUBTRACT')
    sb.inputs[1].default_value = 0.5
    L(nt, fr.outputs[0], sb.inputs[0])
    ab = N(nt, 'ShaderNodeMath', -50, 0, operation='ABSOLUTE')
    L(nt, sb.outputs[0], ab.inputs[0])
    ln = N(nt, 'ShaderNodeMapRange', 100, 0)
    ln.inputs['From Min'].default_value = 0.455
    ln.inputs['From Max'].default_value = 0.488
    ln.inputs['To Min'].default_value = 0.0
    ln.inputs['To Max'].default_value = 1.0
    L(nt, ab.outputs[0], ln.inputs['Value'])
    cm = N(nt, 'ShaderNodeMix', 400, 100, data_type='RGBA')
    cm.inputs[6].default_value = lin4("181B20")
    cm.inputs[7].default_value = lin4("353C46")
    L(nt, ln.outputs['Result'], cm.inputs[0])
    L(nt, cm.outputs[2], b.inputs['Base Color'])
    gv = N(nt, 'ShaderNodeValue', 400, -200)
    GLOW.append((gv.outputs[0], 0.35))
    gv.outputs[0].default_value = 0.35
    em = N(nt, 'ShaderNodeMath', 600, -200, operation='MULTIPLY')
    L(nt, ln.outputs['Result'], em.inputs[0])
    L(nt, gv.outputs[0], em.inputs[1])
    b.inputs['Emission Color'].default_value = lin4(ACCENT_HEX)
    L(nt, rgb_node(nt, 100, -500), b.inputs['Emission Color'])
    L(nt, em.outputs[0], b.inputs['Emission Strength'])
    L(nt, b.outputs['BSDF'], out.inputs['Surface'])
    return m


def sky_mat():
    """Backdrop seen through the window: horizon->zenith gradient, stars and a moon (all keyed)."""
    m, nt = new_mat("Sky")
    out = N(nt, 'ShaderNodeOutputMaterial', 1400, 0)
    em = N(nt, 'ShaderNodeEmission', 1150, 0)
    tc = N(nt, 'ShaderNodeTexCoord', -900, 0)
    sep = N(nt, 'ShaderNodeSeparateXYZ', -700, 200)
    L(nt, tc.outputs['Object'], sep.inputs['Vector'])
    mr = N(nt, 'ShaderNodeMapRange', -500, 200)
    mr.inputs['From Min'].default_value = 0.0
    mr.inputs['From Max'].default_value = 190.0
    L(nt, sep.outputs['Z'], mr.inputs['Value'])
    ch = N(nt, 'ShaderNodeRGB', -500, 450)
    cz = N(nt, 'ShaderNodeRGB', -500, 350)
    gr = N(nt, 'ShaderNodeMix', -250, 300, data_type='RGBA')
    L(nt, mr.outputs['Result'], gr.inputs[0])
    L(nt, ch.outputs[0], gr.inputs[6])
    L(nt, cz.outputs[0], gr.inputs[7])
    # stars
    vo = N(nt, 'ShaderNodeTexVoronoi', -700, -150)
    vo.feature = 'F1'
    vo.inputs['Scale'].default_value = 0.11
    L(nt, tc.outputs['Object'], vo.inputs['Vector'])
    sm = N(nt, 'ShaderNodeMapRange', -500, -150)
    sm.inputs['From Min'].default_value = 0.0
    sm.inputs['From Max'].default_value = 0.022
    sm.inputs['To Min'].default_value = 1.0
    sm.inputs['To Max'].default_value = 0.0
    L(nt, vo.outputs['Distance'], sm.inputs['Value'])
    sg = N(nt, 'ShaderNodeValue', -500, -300)
    sm2 = N(nt, 'ShaderNodeMath', -300, -150, operation='MULTIPLY')
    L(nt, sm.outputs['Result'], sm2.inputs[0])
    L(nt, sg.outputs[0], sm2.inputs[1])
    # moon
    mv = N(nt, 'ShaderNodeVectorMath', -700, -450, operation='DISTANCE')
    mv.inputs[1].default_value = (-82.0, 0.0, 84.0)
    L(nt, tc.outputs['Object'], mv.inputs[0])
    mm = N(nt, 'ShaderNodeMapRange', -500, -450)
    mm.inputs['From Min'].default_value = 5.6
    mm.inputs['From Max'].default_value = 4.9
    mm.inputs['To Min'].default_value = 0.0
    mm.inputs['To Max'].default_value = 1.0
    L(nt, mv.outputs['Value'], mm.inputs['Value'])
    mg = N(nt, 'ShaderNodeValue', -500, -600)
    mm2 = N(nt, 'ShaderNodeMath', -300, -450, operation='MULTIPLY')
    L(nt, mm.outputs['Result'], mm2.inputs[0])
    L(nt, mg.outputs[0], mm2.inputs[1])
    # compose
    add = N(nt, 'ShaderNodeMath', -100, -300, operation='ADD')
    L(nt, sm2.outputs[0], add.inputs[0])
    L(nt, mm2.outputs[0], add.inputs[1])
    comb = N(nt, 'ShaderNodeCombineColor', 200, -300)
    for k, w in (('Red', 0.85), ('Green', 0.92), ('Blue', 1.0)):
        sc = N(nt, 'ShaderNodeMath', 50, -300, operation='MULTIPLY')
        sc.inputs[1].default_value = w
        L(nt, add.outputs[0], sc.inputs[0])
        L(nt, sc.outputs[0], comb.inputs[k])
    tot = N(nt, 'ShaderNodeMix', 500, 100, data_type='RGBA', blend_type='ADD')
    tot.inputs[0].default_value = 1.0
    L(nt, gr.outputs[2], tot.inputs[6])
    L(nt, comb.outputs['Color'], tot.inputs[7])
    L(nt, tot.outputs[2], em.inputs['Color'])
    L(nt, em.outputs['Emission'], out.inputs['Surface'])
    SKY.update(h=ch.outputs[0], z=cz.outputs[0], s=em.inputs['Strength'], star=sg.outputs[0], moon=mg.outputs[0])
    return m


def build_window(parent):
    x0, x1, z0, z1 = WIN
    cx, w, h = (x0 + x1) / 2, x1 - x0, z1 - z0
    wall = simple_mat("Wall", WALL_HEX, rough=0.9, bump=0.12, bump_scale=700.0)
    th = 8.0

    def piece(name, a0, a1, b0, b1):
        mk(name, box_mesh(name, (a1 - a0, th, b1 - b0), off=((a0 + a1) / 2, 82.0 + th / 2, (b0 + b1) / 2)),
           mat=wall, parent=parent, smooth=False)
    piece("WallL", -900.0, x0, 0.0, 400.0)
    piece("WallR", x1, 900.0, 0.0, 400.0)
    piece("WallB", x0, x1, 0.0, z0)
    piece("WallT", x0, x1, z1, 400.0)
    paint = simple_mat("WinPaint", "ECE8DE", rough=0.42)
    fy = 85.5

    def bar(name, c, size):
        mk(name, box_mesh(name, size, bevel=0.2, seg=2), c, paint, parent)
    bar("FrameT", (cx, fy, z1 - 1.8), (w, 3.0, 3.6))
    bar("FrameB", (cx, fy, z0 + 1.8), (w, 3.0, 3.6))
    bar("FrameL", (x0 + 1.8, fy, (z0 + z1) / 2), (3.6, 3.0, h))
    bar("FrameR", (x1 - 1.8, fy, (z0 + z1) / 2), (3.6, 3.0, h))
    bar("Mullion", (cx, fy, (z0 + z1) / 2), (2.6, 2.6, h))
    bar("Transom", (cx, fy, z0 + h * 0.62), (w, 2.6, 2.6))
    bar("Sill", (cx, 82.0 - 3.0, z0 - 0.6), (w + 10.0, 14.0, 2.4))
    sky = bpy.data.meshes.new("SkyPlane")
    sky.from_pydata([(-520, 0, -120), (320, 0, -120), (320, 0, 330), (-520, 0, 330)], [], [(0, 1, 2, 3)])
    so = mk("Sky", sky, (0, 150.0, 0), sky_mat(), parent, smooth=False)
    so.visible_shadow = False            # the backdrop must not block the sun


def build_speaker(parent, x, y, yaw):
    root = empty("Speaker", (x, y, 0.0), parent)
    root.rotation_euler = (0, 0, math.radians(yaw))
    R, zc = 7.4, 9.4
    prof = [(0.0, 1.8)] + [(R * math.cos(math.radians(a)), zc + R * math.sin(math.radians(a)))
                          for a in range(-70, 91, 10)]
    m, nt = new_mat("SpeakerBody")
    out = N(nt, 'ShaderNodeOutputMaterial', 900, 0)
    b = N(nt, 'ShaderNodeBsdfPrincipled', 600, 0)
    b.inputs['Roughness'].default_value = 0.55
    b.inputs['Sheen Weight'].default_value = 0.4
    tc = N(nt, 'ShaderNodeTexCoord', -500, 0)
    dv = N(nt, 'ShaderNodeVectorMath', -300, 0, operation='DISTANCE')
    dv.inputs[1].default_value = (0.0, -R, zc)
    L(nt, tc.outputs['Object'], dv.inputs[0])
    mk_ = N(nt, 'ShaderNodeMapRange', -100, 0)
    mk_.inputs['From Min'].default_value = 4.6
    mk_.inputs['From Max'].default_value = 4.1
    L(nt, dv.outputs['Value'], mk_.inputs['Value'])
    mx = N(nt, 'ShaderNodeMix', 200, 100, data_type='RGBA')
    mx.inputs[6].default_value = lin4("2A2D33")
    mx.inputs[7].default_value = lin4("0B0C0E")
    L(nt, mk_.outputs['Result'], mx.inputs[0])
    L(nt, mx.outputs[2], b.inputs['Base Color'])
    L(nt, b.outputs['BSDF'], out.inputs['Surface'])
    mk("SpkBody", lathe(prof, 56, "SpkM"), mat=m, parent=root)
    ring = lathe([(3.6, 0.0), (5.6, 0.0), (5.6, 0.9), (3.6, 0.9), (3.6, 0.0)], 56, "SpkRing")
    mk("SpkRing", ring, mat=glow_mat("SpkGlow", 3.6, wave=True), parent=root)
    ld = bpy.data.lights.new("SpkLight", 'POINT')
    ld.shadow_soft_size = 2.5
    ld.color = hex_lin(ACCENT_HEX)
    o = link(bpy.data.objects.new("SpkLight", ld), root)
    o.location = (0, -2.0, 3.0)
    o.visible_camera = False
    HW_LIGHTS.append((ld, 700.0, o))


# ---- PC tower ---------------------------------------------------------------
_FAN = {}


def fan_meshes(R):
    if R in _FAN:
        return _FAN[R]
    th = 2.4
    dark = simple_mat("FanDark" + str(R), "111215", rough=0.45)
    ring_m = simple_mat("FanRingSlot", "000000")      # replaced per fan by an object-level RGB material
    fr = lathe([(R - 1.1, 0), (R, 0), (R, th), (R - 1.1, th), (R - 1.1, 0)], 48, "FanFrame")
    fr.materials.append(dark)
    gl = lathe([(R - 2.7, th - 0.3), (R - 1.5, th - 0.3), (R - 1.5, th + 0.05), (R - 2.7, th + 0.05),
                (R - 2.7, th - 0.3)], 48, "FanGlow")
    gl.materials.append(ring_m)
    hub = lathe([(0, 0.2), (R * 0.30, 0.2), (R * 0.30, th * 0.8), (R * 0.24, th * 0.95), (0, th * 0.95)], 32, "FanHub")
    hub.materials.append(dark)
    bm = bmesh.new()
    n = 9
    r0, r1 = R * 0.28, R - 2.8
    for i in range(n):
        t0 = 2 * math.pi * i / n
        grid = []
        for ku in range(5):
            u = ku / 4
            row = []
            for v in (-1.0, 0.0, 1.0):
                a = t0 + v * (0.15 + 0.10 * u) + 0.6 * u * u
                r = r0 + (r1 - r0) * u
                row.append(bm.verts.new((r * math.cos(a), r * math.sin(a), 1.2 + v * 0.5 * (0.4 + 0.6 * u))))
            grid.append(row)
        for ku in range(4):
            for kv in range(2):
                bm.faces.new((grid[ku][kv], grid[ku][kv + 1], grid[ku + 1][kv + 1], grid[ku + 1][kv]))
    bl = bpy.data.meshes.new("FanBlades")
    bm.to_mesh(bl)
    bm.free()
    for p in bl.polygons:
        p.use_smooth = True
    bl.materials.append(simple_mat("FanBlade" + str(R), "1E2025", rough=0.35, coat=0.3))
    _FAN[R] = (fr, gl, hub, bl)
    return _FAN[R]


def build_fan(parent, name, loc, R, rot, turns=1.5):
    root = empty(name, loc, parent)
    root.rotation_euler = rot
    fr, gl, hub, bl = fan_meshes(R)
    link(bpy.data.objects.new(name + "Fr", fr), root)
    glo = link(bpy.data.objects.new(name + "Gl", gl), root)
    glo.material_slots[0].link = 'OBJECT'
    glo.material_slots[0].material = glow_mat("FanRing_" + name, 4.4, wave=True)
    rotor = empty(name + "Rotor", (0, 0, 0), root)
    link(bpy.data.objects.new(name + "Hub", hub), rotor)
    link(bpy.data.objects.new(name + "Bl", bl), rotor)
    SPINNERS.append((rotor, (11.0 + 2.5 * (len(SPINNERS) % 4)) * (1 if len(SPINNERS) % 3 else -1)))
    return root


def tube(parent, name, pts, r, mat):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = r
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    sp = cu.splines.new('POLY')
    n = 32
    sp.points.add(n)
    p0, p1, p2, p3 = (Vector(p) for p in pts)
    for i in range(n + 1):
        t = i / n
        q = p0 * (1 - t) ** 3 + p1 * 3 * t * (1 - t) ** 2 + p2 * 3 * t * t * (1 - t) + p3 * t ** 3
        sp.points[i].co = (q.x, q.y, q.z, 1.0)
    cu.materials.append(mat)
    return link(bpy.data.objects.new(name, cu), parent)


def hw_light(parent, name, kind, loc, energy, rot=None, size=4.0, size_y=None, color=None):
    ld = bpy.data.lights.new(name, kind)
    ld.color = color or hex_lin(ACCENT_HEX)
    if kind == 'AREA':
        ld.shape = 'RECTANGLE'
        ld.size, ld.size_y = size, size_y or size
    else:
        ld.shadow_soft_size = size
    o = link(bpy.data.objects.new(name, ld), parent)
    o.location = loc
    if rot:
        o.rotation_euler = rot
    o.visible_camera = False
    HW_LIGHTS.append((ld, energy, o if color is None else None))
    return o


def build_tower(parent):
    TW, TD, TH, t = 84.0, 32.0, 76.0, 1.2
    root = empty("Tower", (112.0, 50.0, 0.0), parent)
    root.rotation_euler = (0, 0, math.radians(-13.0))
    shell = simple_mat("CaseShell", "202228", rough=0.42, metal=0.55, bump=0.1, bump_scale=140)
    inner = simple_mat("CaseInner", "2B2E37", rough=0.5, metal=0.25)
    heat = simple_mat("Heatsink", "3A3D46", rough=0.32, metal=0.75, bump=0.2, bump_scale=160)
    pcb = simple_mat("Pcb", "262A33", rough=0.5, bump=0.3, bump_scale=70)
    rubber = simple_mat("HoseRubber", "0B0B0D", rough=0.4, sheen=0.3)

    def box(name, size, c, mat, bevel=0.0):
        return mk(name, box_mesh(name, size, bevel=bevel, seg=2), c, mat, root, smooth=bevel > 0)
    box("Back", (TW, t, TH), (0, TD / 2 - t / 2, TH / 2), inner)
    box("Floor", (TW, TD, t), (0, 0, t / 2), shell, 0.2)
    box("Roof", (TW, TD, t), (0, 0, TH - t / 2), shell, 0.2)
    box("Front", (t, TD, TH), (-TW / 2 + t / 2, 0, TH / 2), shell)
    box("Rear", (t, TD, TH), (TW / 2 - t / 2, 0, TH / 2), shell)
    # tempered glass (no shadow, no refraction) + bezel
    g = box("Glass", (TW - 0.4, 0.4, TH - 0.4), (0, -TD / 2 - 0.1, TH / 2), glossy_glass("TemperedGlass"))
    g.visible_shadow = False
    for nm, sz, c in (("BzT", (TW, 0.9, 1.5), (0, -TD / 2 - 0.45, TH - 0.75)),
                      ("BzB", (TW, 0.9, 1.5), (0, -TD / 2 - 0.45, 0.75)),
                      ("BzL", (1.5, 0.9, TH), (-TW / 2 + 0.75, -TD / 2 - 0.45, TH / 2)),
                      ("BzR", (1.5, 0.9, TH), (TW / 2 - 0.75, -TD / 2 - 0.45, TH / 2))):
        box(nm, sz, c, shell, 0.1)
    box("FrontStrip", (0.3, 1.0, 54.0), (-TW / 2 - 0.1, -TD / 2 + 4.0, TH / 2), glow_mat("FrontStrip", 3.2, wave=True), 0.05)
    # motherboard + parts (back plane)
    my = TD / 2 - t - 1.9
    box("Mobo", (50.0, 0.8, 60.0), (13.0, my, 40.0), pcb, 0.1)
    box("Vrm", (14.0, 3.5, 12.0), (-4.0, my - 2.1, 62.0), heat, 0.3)
    box("IoCover", (6.0, 3.5, 30.0), (34.5, my - 2.1, 52.0), heat, 0.3)
    box("Psu", (52.0, 12.0, 7.0), (12.0, 8.0, 4.8), inner, 0.2)
    box("PsuLine", (50.0, 0.3, 0.5), (12.0, 1.85, 8.3), glow_mat("PsuLine", 3.0, wave=True), 0.05)
    # AIO pump block with a lit cap
    pump = empty("Pump", (6.0, my - 0.4, 46.0), root)
    pump.rotation_euler = (math.pi / 2, 0, 0)
    mk("PumpBody", lathe([(0, 0), (6.4, 0), (6.4, 3.6), (5.6, 4.0), (0, 4.0)], 40, "PumpM"), mat=heat, parent=pump)
    mk("PumpCap", lathe([(0, 4.05), (4.3, 4.05)], 40, "PumpCapM"), mat=glow_mat("PumpCap", 3.6, wave=True), parent=pump)
    mk("PumpHub", lathe([(0, 4.1), (1.5, 4.1), (1.5, 4.3), (0, 4.3)], 24, "PumpHubM"),
       mat=simple_mat("PumpLogo", "0B0B0D", rough=0.3), parent=pump)
    # radiator + three front fans (side-mounted, ring-lit)
    box("Radiator", (18.0, 4.0, 66.0), (-30.0, -8.6, 36.5), heat, 0.2)
    for z in (14.5, 36.5, 58.5):
        build_fan(root, f"RadFan{z}", (-30.0, -10.6, z), 9.0, (math.pi / 2, 0, 0), 1.2)
    tube(root, "HoseA", [(-33, -8.6, 70), (-33, -6.0, 74), (-14, my - 2, 49.6), (0.3, my - 2, 49.6)], 1.15, rubber)
    tube(root, "HoseB", [(-27, -8.6, 70), (-27, -4.0, 73), (-14, my - 2, 42.8), (0.3, my - 2, 42.8)], 1.15, rubber)
    # RAM, lit
    ram_body = simple_mat("RamBody", "17181C", rough=0.35, metal=0.6)
    ram_glow = glow_mat("RamLight", 4.0, wave=True)
    for i in range(4):
        x = 18.5 + 2.9 * i
        box(f"Ram{i}", (1.4, 3.0, 28.0), (x, my - 1.9, 54.0), ram_body, 0.1)
        box(f"RamL{i}", (1.1, 3.2, 6.5), (x, my - 2.0, 65.0), ram_glow, 0.1)
    # graphics card: long axis horizontal, three fans toward the glass, lit edge strip
    box("Gpu", (52.0, 7.0, 20.0), (12.0, 0.0, 19.0), heat, 0.5)
    for k, x in enumerate((-5.5, 12.0, 29.5)):
        build_fan(root, f"GpuFan{k}", (x, -3.5, 19.0), 7.8, (math.pi / 2, 0, 0), 1.6)
    box("GpuEdge", (48.0, 1.3, 1.0), (12.0, -3.4, 29.6), glow_mat("GpuEdge", 4.0, wave=True), 0.1)
    cu = bpy.data.curves.new("GpuText", 'FONT')
    cu.body, cu.size, cu.extrude, cu.align_x, cu.align_y = "RTX 5090", 1.45, 0.05, 'CENTER', 'CENTER'
    cu.materials.append(glow_mat("GpuLabel", 3.0, wave=True))
    to = link(bpy.data.objects.new("GpuText", cu), root)
    to.location = (12.0, -3.55, 9.9)
    to.rotation_euler = (math.pi / 2, 0, 0)
    # bottom row, top row and rear fan
    for k, x in enumerate((-2.0, 17.0)):
        build_fan(root, f"BotFan{k}", (x, -9.0, t), 7.2, (0, 0, 0), 1.0)
    for k, x in enumerate((-2.0, 20.0)):
        build_fan(root, f"TopFan{k}", (x, -3.0, TH - t), 8.6, (math.pi, 0, 0), 1.0)
    build_fan(root, "RearFan", (TW / 2 - t, -3.0, 58.0), 8.2, (0, -math.pi / 2, 0), 1.0)
    # interior + spill lights: every one follows the RGB wave at its own position (see the key loop)
    for k, z in enumerate((14.5, 36.5, 58.5)):
        hw_light(root, f"RadGlow{k}", 'AREA', (-30.0, -13.5, z), 6000.0, (-math.pi / 2, 0, 0), 16.0, 16.0)
    for k, x in enumerate((-5.5, 12.0, 29.5)):
        hw_light(root, f"GpuGlow{k}", 'AREA', (x, -8.5, 19.0), 4500.0, (-math.pi / 2, 0, 0), 15.0, 15.0)
    hw_light(root, "GpuEdgeGlow", 'AREA', (12.0, -7.0, 31.0), 1200.0, (-math.pi / 2, 0, 0), 48.0, 3.0)
    hw_light(root, "PumpGlow", 'POINT', (6.0, 3.0, 46.0), 1600.0, None, 3.0)
    hw_light(root, "RamGlow", 'POINT', (24.0, 3.0, 64.0), 900.0, None, 3.0)
    hw_light(root, "TopGlow", 'AREA', (9.0, -4.0, TH - 3.0), 1400.0, (0, 0, 0), 40.0, 10.0)
    hw_light(root, "FloorGlow", 'AREA', (8.0, -8.0, 3.0), 1700.0, (-math.pi / 2, 0, 0), 40.0, 4.0)
    hw_light(root, "SideStripGlow", 'AREA', (-TW / 2 - 1.5, -TD / 2 + 4.0, TH / 2), 2600.0, (0, math.pi / 2, 0), 4.0, 54.0)
    hw_light(root, "DeskSpill", 'AREA', (6.0, -TD / 2 - 3.0, 34.0), 22000.0, (math.radians(-74.0), 0, 0), 70.0, 28.0)
    hw_light(root, "CaseFill", 'AREA', (12.0, -12.0, 40.0), 90000.0, (math.pi / 2, 0, 0), 60.0, 56.0,
             color=(0.40, 0.50, 1.0))                     # cool fill so the board, PSU and hoses read through the glass
    return root


def build_room_shell(parent):
    dmesh = bpy.data.meshes.new("DeskMesh")
    dmesh.from_pydata([(-700, -520, 0), (700, -520, 0), (700, 82, 0), (-700, 82, 0)], [], [(0, 1, 2, 3)])
    mk("Desk", dmesh, mat=desk_material(), parent=parent, smooth=False)
    build_window(parent)
    mk("Mat", box_mesh("Mat", (118.0, 56.0, 0.35), bevel=0.12, plan_r=3.0, seg=3, off=(0, 0, 0.175)),
       (14.0, 0.0, 0.0), topo_mat(), parent)
    build_props(parent)
    build_speaker(parent, -58.0, 50.0, 12.0)
    build_speaker(parent, 56.0, 50.0, -12.0)
    build_tower(parent)


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
    light.inputs['Strength'].default_value = 0.5
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
# static wide framing, held from frame 1 until CAM_START (day turns to night first)
WIDE_T = Vector((8.0, 30.0, 30.0))
WIDE_CAM = (-100.0, 21.0, 232.0, 22.0, 0.0095)        # az, el, dist, lens, fstop


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
    ws = [(CAM_START, WIDE_T), (120, Vector((10, 12, 14))), (160, Vector((1.0, -1.0, 3.0))),
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
        (CAM_START, *WIDE_CAM),
        (120, -105, 28, 164, 47, 0.0172),
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
            fp0 = KBC.lerp(Vector((0.0, 50.0, 38.0)), 0.30)       # wide shot: between keyboard and monitor
            fp = fp0.lerp(KBC.lerp(JK0, ease((f - CAM_START) / 100.0)), ease((f - CAM_START) / 20.0))
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

    # ---- lights ------------------------------------------------------------
    # window sun (warm, low) + sky panel in the opening + cool room fill + monitor + light bar
    x0, x1, z0, z1 = WIN
    sun_obj, sun = add_light("Sun", 'SUN', (0, 0, 50), SUN_ENERGY, color=(1.0, 0.80, 0.58))
    sun.angle = math.radians(1.6)
    sun_obj.rotation_mode = 'QUATERNION'
    sky_ob, skyl = add_light("SkyPanel", 'AREA', ((x0 + x1) / 2, 85.0, (z0 + z1) / 2), SKY_ENERGY,
                             (0.85, 0.9, 1.0), None, x1 - x0, z1 - z0)
    sky_ob.rotation_euler = (-math.pi / 2, 0, 0)
    sky_ob.visible_camera = False
    sky_ob.visible_glossy = False          # no giant window reflection in the case glass
    scr_tgt = empty("ScreenTarget", (0, 4.0, 3.0))
    glow_ob, glow = add_light("ScreenGlow", 'AREA', (0, 51.5, 40.0), SCREEN_ENERGY, (0.42, 0.62, 1.0), scr_tgt, 66.0,
                              34.0, parent=ws)
    fill_tgt = empty("FillTarget", (10.0, 8.0, 8.0))
    fill_ob, fillw = add_light("RoomFill", 'AREA', (70.0, -120.0, 85.0), FILL_ENERGY, (0.66, 0.78, 1.0), fill_tgt, 70.0)
    kb_tgt = empty("BarTarget", (0, -4.0, 2.0))
    bar_ob, barl = add_light("BarLight", 'AREA', (0, 49.0, 63.0), BAR_ENERGY, (1.0, 0.58, 0.32), kb_tgt, 34.0, 7.0,
                             parent=ws)
    kk_ob, kkl = add_light("KeyboardKey", 'AREA', (-6.0, -34.0, 34.0), KBKEY_ENERGY, (1.0, 0.5, 0.26), kb_tgt, 30.0,
                           14.0)
    hk_ob, hkl = add_light("HeroKeyLight", 'AREA', JK0 + Vector((-4.0, -22.0, 24.0)), HERO_ENERGY, (1.0, 0.72, 0.52),
                           hero, 9.0, 9.0)
    amb_ob, amb = add_light("MonAmbient", 'AREA', (0.0, 60.0, 40.0), 6000.0, (1, 1, 1), None, 70.0, 40.0, parent=ws)
    amb_ob.rotation_euler = (math.pi / 2, 0, 0)          # faces the wall behind the monitor
    HW_LIGHTS.append((amb, 6000.0, amb_ob))
    for o_ in (sun_obj, glow_ob, fill_ob, bar_ob, kk_ob, hk_ob, amb_ob):
        o_.visible_camera = False
    

    target = hero
    strip_a, sa = add_light("StripA", 'AREA', HERO_H + Vector((-19, 7, 3)), 0.0, (1.0, 0.95, 0.9), target,
                            3.0, 26.0)
    strip_b, sb = add_light("StripB", 'AREA', HERO_H + Vector((19, 7, 3)), 0.0, (0.85, 0.92, 1.0), target,
                            3.0, 26.0)
    fill_o, sf = add_light("StudioFill", 'AREA', HERO_H + Vector((0, -30, 16)), 0.0, (1, 0.97, 0.95), target, 14.0)
    for ld in [sun, skyl, fillw, glow, barl, kkl, hkl] + [ld for ld, _e, _o in HW_LIGHTS] + [sa, sb, sf]:
        ld.use_shadow = True

    # ---- haze: two small homogeneous volumes (cheap): sun shafts at the window by day, coloured haze round the rig
    def haze_box(name, x0_, x1_, y0_, y1_, z1_, color):
        hm_, hnt_ = new_mat(name)
        ho_ = N(hnt_, 'ShaderNodeOutputMaterial', 600, 0)
        hs_ = N(hnt_, 'ShaderNodeVolumeScatter', 300, 0)
        hs_.inputs['Anisotropy'].default_value = 0.45
        hs_.inputs['Color'].default_value = (*color, 1.0)
        L(hnt_, hs_.outputs[0], ho_.inputs['Volume'])
        # soft ellipsoid falloff so the box walls never show
        cen = ((x0_ + x1_) / 2, (y0_ + y1_) / 2, 2.0 + (z1_ - 2.0) / 2)
        rad = ((x1_ - x0_) / 2, (y1_ - y0_) / 2, (z1_ - 2.0) / 2)
        gp_ = N(hnt_, 'ShaderNodeNewGeometry', -600, 0)
        sb_ = N(hnt_, 'ShaderNodeVectorMath', -400, 0, operation='SUBTRACT')
        sb_.inputs[1].default_value = cen
        dv_ = N(hnt_, 'ShaderNodeVectorMath', -200, 0, operation='DIVIDE')
        dv_.inputs[1].default_value = rad
        ln_ = N(hnt_, 'ShaderNodeVectorMath', 0, 0, operation='LENGTH')
        mr_ = N(hnt_, 'ShaderNodeMapRange', 150, 0)
        mr_.inputs['From Min'].default_value = 0.35
        mr_.inputs['From Max'].default_value = 0.98
        mr_.inputs['To Min'].default_value = 1.0
        mr_.inputs['To Max'].default_value = 0.0
        mr_.interpolation_type = 'SMOOTHSTEP'
        dn_ = N(hnt_, 'ShaderNodeValue', 150, -200)
        mu_ = N(hnt_, 'ShaderNodeMath', 450, 0, operation='MULTIPLY')
        L(hnt_, gp_.outputs['Position'], sb_.inputs[0])
        L(hnt_, sb_.outputs[0], dv_.inputs[0])
        L(hnt_, dv_.outputs[0], ln_.inputs[0])
        L(hnt_, ln_.outputs['Value'], mr_.inputs['Value'])
        L(hnt_, mr_.outputs['Result'], mu_.inputs[0])
        L(hnt_, dn_.outputs[0], mu_.inputs[1])
        L(hnt_, mu_.outputs[0], hs_.inputs['Density'])
        try:
            hm_.cycles.volume_sampling = 'DISTANCE'
            hm_.cycles.volume_step_rate = 4.0
        except Exception as e:
            print("volume sampling:", e)
        ht_ = N(hnt_, 'ShaderNodeBsdfTransparent', 300, -150)
        L(hnt_, ht_.outputs[0], ho_.inputs['Surface'])
        ob_ = mk(name, box_mesh(name, (x1_ - x0_, y1_ - y0_, z1_ - 2.0), off=(0, 0, 0)),
                 ((x0_ + x1_) / 2, (y0_ + y1_) / 2, 2.0 + (z1_ - 2.0) / 2), hm_, smooth=False)   # clear of the desk/wall planes
        return ob_, dn_.outputs[0]
    haze_d, HZ_D = haze_box("HazeDay", -250.0, 30.0, -60.0, 80.0, 190.0, (1.0, 0.92, 0.78))
    haze_n, HZ_N = haze_box("HazeNight", -80.0, 260.0, -110.0, 80.0, 170.0, (0.9, 0.92, 1.0))
    haze = haze_d

    # one frame list for every room light / emissive / sky key
    FR = sorted(set(list(range(1, 101, 3)) + [100, 110, 120, 130, 140, 145, 160, 180, 200, 205]
                    + list(range(206, 246, 2)) + [246, 480]))

    def room(f, v):
        """Room-light value `v` with the 205-228 fade-out that leaves the studio black."""
        return v * (fall(f) if f >= 205 else 1.0) if f < 246 else 0.0

    for f in FR:
        n_ = night(f)
        sd = sun_dir(f)
        sun_obj.rotation_quaternion = sd.to_track_quat('-Z', 'Y')
        sun_obj.keyframe_insert('rotation_quaternion', frame=f)
        sun.color = pwl(f, SUN_ROWS, 1)
        sun.energy = room(f, SUN_ENERGY * sunvis(f))
        skyl.color = pwl(f, SKYL_ROWS, 1)
        skyl.energy = room(f, SKY_ENERGY * pwl(f, SKYL_ROWS, 2))
        cc_ = ease((f - 14.0) / 34.0)                   # cool fill arrives early so dusk is warm sky vs blue room
        fillw.color = tuple(a + (b - a) * cc_ for a, b in zip((0.80, 0.86, 1.0), (0.14, 0.30, 1.0)))
        fillw.energy = room(f, FILL_ENERGY * (1.0 - n_) + FILL_NIGHT * n_)
        glow.energy = room(f, SCREEN_ENERGY * (0.55 + 3.2 * n_))
        barl.energy = room(f, BAR_ENERGY * (0.15 + 0.85 * n_))
        kkl.energy = room(f, KBKEY_ENERGY * n_ * (0.5 + 0.5 * ease((f - 110.0) / 40.0)))
        hkl.energy = room(f, HERO_ENERGY * ease((f - 125.0) / 55.0))
        for ld in (sun, skyl, fillw, glow, barl, kkl, hkl):
            ld.keyframe_insert('energy', frame=f)
        for ld in (sun, skyl, fillw):
            ld.keyframe_insert('color', frame=f)
        # hardware emission (static colours and strengths; the RGB wave is keyed per frame below)
        for sock, base in GLOW:
            sock.default_value = base * gmul(f) if f < 246 else 0.0
            sock.keyframe_insert('default_value', frame=f)
        HZ_D.default_value = max(0.0, room(f, HAZE_DAY * sunvis(f) ** 1.5) - 4e-4)
        HZ_N.default_value = max(0.0, room(f, HAZE_NIGHT * night(f) * (1.0 - ease((f - 100.0) / 30.0))) - 1e-4)   # volumes cost ~2x: only where seen
        for hz_, hob_ in ((HZ_D, haze_d), (HZ_N, haze_n)):
            hz_.keyframe_insert('default_value', frame=f)
            hob_.hide_render = f >= 230 or hz_.default_value <= 0.0
            hob_.keyframe_insert('hide_render', frame=f)
        # sky seen through the window
        sr = pwl(f, SKY_ROWS, 3)
        SKY['h'].default_value = (*pwl(f, SKY_ROWS, 1), 1.0)
        SKY['z'].default_value = (*pwl(f, SKY_ROWS, 2), 1.0)
        SKY['s'].default_value = room(f, sr)
        SKY['star'].default_value = 2.2 * ease((f - 58.0) / 24.0)
        SKY['moon'].default_value = 1.1 * ease((f - 62.0) / 24.0)
        for k in ('h', 'z', 's', 'star', 'moon'):
            SKY[k].keyframe_insert('default_value', frame=f)
    # ---- RGB wave: one deterministic function of the frame drives shaders and spill lights -------------
    bpy.context.view_layer.update()
    hw_pos = [(ld, e0, (ob.matrix_world.translation.copy() if ob is not None else None)) for ld, e0, ob in HW_LIGHTS]
    for f in range(1, 247):
        g = gmul(f) if f < 246 else 0.0
        for tv in HUE_NODES:
            tv.outputs[0].default_value = f / HUE_P
            tv.outputs[0].keyframe_insert('default_value', frame=f)
        for ld, e0, pos in hw_pos:
            if pos is not None:
                ld.color = hue_rgb(hue_at(f, pos))
                ld.keyframe_insert('color', frame=f)
            ld.energy = e0 * g
            ld.keyframe_insert('energy', frame=f)
    for rotor, dps in SPINNERS:                # degrees per frame, a pure function of the frame
        for f in range(1, 252):
            rotor.rotation_euler = (0, 0, math.radians(dps * (f - 1)))
            rotor.keyframe_insert('rotation_euler', frame=f)
    # rim lights (kept lit on the key) ramp in as the room falls away
    ENG = dict(A=9000.0, B=8000.0, F=2800.0)
    for ld, e in ((sa, ENG['A']), (sb, ENG['B']), (sf, ENG['F'])):
        keys = [(1, 0.0), (205, 0.0)] + [(f, e * ease((f - 205) / 32.0)) for f in range(206, 238)]
        keys += [(400, e), (450, e * (2.8 if ld is sf else 1.0)), (480, e * (2.8 if ld is sf else 1.0))]
        for f, v in keys:
            ld.energy = v
            ld.keyframe_insert('energy', frame=f)
    # world: ambient fill follows the sky -> 0 ; camera-ray background -> exactly BLACK_HEX by 235
    wl = lin4(WALL_HEX)
    bl = lin4(BLACK_HEX)
    for f in sorted(set(FR + list(range(205, 246)))):
        w_ = fall(f, 207.0, 226.0, 2.4) if f < 480 else 0.0
        bg_light.inputs['Color'].default_value = (*pwl(f, WORLD_ROWS, 1), 1.0)
        bg_light.inputs['Color'].keyframe_insert('default_value', frame=f)
        bg_light.inputs['Strength'].default_value = pwl(f, WORLD_ROWS, 2) * w_
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
    setup_bloom()
    scene.frame_set(1)


def setup_bloom():
    """Cheap compositor bloom around the emitters (strength keyed to 0 well before the studio frames)."""
    try:
        ng = bpy.data.node_groups.new("Comp", 'CompositorNodeTree')
        ng.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
        rl = ng.nodes.new('CompositorNodeRLayers')
        gl = ng.nodes.new('CompositorNodeGlare')
        out = ng.nodes.new('NodeGroupOutput')
        gl.inputs['Type'].default_value = 'Bloom'
        gl.inputs['Threshold'].default_value = 1.0
        gl.inputs['Size'].default_value = 0.55
        ng.links.new(rl.outputs['Image'], gl.inputs['Image'])
        ng.links.new(gl.outputs['Image'], out.inputs[0])
        scene.compositing_node_group = ng
        st = gl.inputs['Strength']
        for f, v in ((1, 0.30), (200, 0.30), (214, 0.0), (480, 0.0)):
            st.default_value = v
            st.keyframe_insert('default_value', frame=f)
    except Exception as e:
        print("bloom setup:", e)


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
        cy = scene.cycles
        cy.use_adaptive_sampling = True
        cy.adaptive_threshold = 0.02
        cy.adaptive_min_samples = 24
        cy.use_denoising = True
        cy.denoiser = 'OPENIMAGEDENOISE'
        for attr, val in (('denoising_prefilter', 'ACCURATE'), ('denoising_input_passes', 'RGB_ALBEDO_NORMAL'),
                          ('denoising_use_gpu', True)):
            try:
                setattr(cy, attr, val)
            except Exception:
                pass
        cy.max_bounces = 6
        cy.diffuse_bounces, cy.glossy_bounces, cy.transparent_max_bounces = 3, 3, 12
        cy.sample_clamp_indirect = 2.5                  # fireflies from emissive-lit dark areas
        cy.caustics_reflective = cy.caustics_refractive = False
        cy.blur_glossy = 0.4
        for attr, val in (('volume_step_rate', 10.0), ('volume_max_steps', 24), ('volume_bounces', 0)):
            try:
                setattr(cy, attr, val)
            except Exception:
                pass
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
