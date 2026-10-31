"""Coherent procedural material palette for SKILL ISSUE.

Bedroom: warm amber practicals against cool monitor blue.
Hall: desaturated steel, rubber, concrete, restrained warning red.
Machine: restrained cyan accents only.
"""

import bpy

_CACHE = {}


class NB:
    """Tiny node-tree builder."""

    def __init__(self, tree):
        self.t = tree
        self.nodes = tree.nodes
        self.links = tree.links

    def n(self, type_, loc=(0, 0), **inputs):
        node = self.nodes.new(type_)
        node.location = loc
        for k, v in inputs.items():
            if k.startswith("_"):
                setattr(node, k[1:], v)
            else:
                key = k if k in node.inputs else k.replace("_", " ")
                node.inputs[key].default_value = v
        return node

    def l(self, out, inp):
        self.links.new(out, inp)


def _new(name):
    m = bpy.data.materials.get(name)
    if m:
        return m, None
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nb = NB(m.node_tree)
    nb.nodes.clear()
    return m, nb


def _principled(nb, color=(0.8, 0.8, 0.8, 1), rough=0.5, metal=0.0, **kw):
    p = nb.n("ShaderNodeBsdfPrincipled", (0, 0))
    p.inputs["Base Color"].default_value = color
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    for k, v in kw.items():
        p.inputs[k].default_value = v
    out = nb.n("ShaderNodeOutputMaterial", (300, 0))
    nb.l(p.outputs[0], out.inputs[0])
    return p, out


def coords(nb, mode="object", loc=(-1100, 0)):
    """Object-space coordinates, or the stored rest pose for deforming meshes."""
    if mode == "rest":
        a = nb.n("ShaderNodeAttribute", loc)
        a.attribute_type = 'GEOMETRY'
        a.attribute_name = "rest_co"
        return a.outputs["Vector"]
    return nb.n("ShaderNodeTexCoord", loc).outputs["Object"]


def _bump(nb, p, height_socket, strength=0.2, distance=0.01):
    b = nb.n("ShaderNodeBump", (-200, -300), Strength=strength, Distance=distance)
    nb.l(height_socket, b.inputs["Height"])
    nb.l(b.outputs[0], p.inputs["Normal"])
    return b


def simple(name, color, rough=0.5, metal=0.0, **kw):
    m, nb = _new(name)
    if nb:
        _principled(nb, color, rough, metal, **kw)
    return m


def skin():
    m, nb = _new("MAT_Skin")
    if nb:
        p, _ = _principled(nb, (0.40, 0.235, 0.15, 1), 0.48)
        p.inputs["Subsurface Weight"].default_value = 0.25
        p.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.2)
        p.inputs["Subsurface Scale"].default_value = 0.02
        p.inputs["Specular IOR Level"].default_value = 0.45
        co = coords(nb, "rest", (-900, 0))
        noise = nb.n("ShaderNodeTexNoise", (-700, 0), Scale=35.0, Detail=3.0)
        nb.l(co, noise.inputs["Vector"])
        # blotchy warm variation (cheeks/nose a touch redder)
        ramp = nb.n("ShaderNodeValToRGB", (-450, 150))
        ramp.color_ramp.elements[0].color = (0.42, 0.21, 0.12, 1)
        ramp.color_ramp.elements[1].color = (0.50, 0.26, 0.15, 1)
        n2 = nb.n("ShaderNodeTexNoise", (-700, 250), Scale=4.0, Detail=2.0)
        nb.l(co, n2.inputs["Vector"])
        nb.l(n2.outputs["Fac"], ramp.inputs["Fac"])
        # rosy cheeks and nose tip, in rest space so they stay put while he acts
        blush = None
        for i, (c, rad, amt) in enumerate((((0.064, -0.124, 1.522), 0.042, 0.55),
                                           ((-0.064, -0.124, 1.522), 0.042, 0.55),
                                           ((0.0, -0.172, 1.522), 0.026, 0.35))):
            d = nb.n("ShaderNodeVectorMath", (-700, 450 + 150 * i), _operation='DISTANCE')
            nb.l(co, d.inputs[0])
            d.inputs[1].default_value = c
            mr = nb.n("ShaderNodeMapRange", (-500, 450 + 150 * i))
            mr.interpolation_type = 'SMOOTHSTEP'
            mr.inputs["From Min"].default_value = rad
            mr.inputs["From Max"].default_value = 0.0
            mr.inputs["To Max"].default_value = amt
            nb.l(d.outputs["Value"], mr.inputs["Value"])
            if blush is None:
                blush = mr.outputs["Result"]
            else:
                mx = nb.n("ShaderNodeMath", (-300, 450 + 150 * i), _operation='MAXIMUM')
                nb.l(blush, mx.inputs[0])
                nb.l(mr.outputs["Result"], mx.inputs[1])
                blush = mx.outputs[0]
        mix = nb.n("ShaderNodeMix", (-200, 150), _data_type='RGBA')
        nb.l(blush, mix.inputs["Factor"])
        nb.l(ramp.outputs[0], mix.inputs[6])
        mix.inputs[7].default_value = (0.60, 0.21, 0.16, 1)
        nb.l(mix.outputs[2], p.inputs["Base Color"])
        _bump(nb, p, noise.outputs["Fac"], 0.02, 0.002)          # smooth animated-feature skin
    return m


def fabric(name, color, scale=180.0, rough=0.85, fold_strength=0.35, sheen=0.4, mode="object"):
    """Knit/cotton fabric: fine weave bump + soft broad folds."""
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, color, rough)
        p.inputs["Sheen Weight"].default_value = sheen
        p.inputs["Sheen Tint"].default_value = (1, 1, 1, 1)
        co = coords(nb, mode, (-1100, 0))
        weave = nb.n("ShaderNodeTexNoise", (-850, -100), Scale=scale * 2.0, Detail=1.0)
        folds = nb.n("ShaderNodeTexNoise", (-850, -350), Scale=6.0, Detail=3.0, Roughness=0.4)
        nb.l(co, weave.inputs["Vector"])
        nb.l(co, folds.inputs["Vector"])
        mix = nb.n("ShaderNodeMath", (-600, -200), _operation='MULTIPLY_ADD')
        nb.l(folds.outputs["Fac"], mix.inputs[0])
        mix.inputs[1].default_value = 6.0 * fold_strength
        nb.l(weave.outputs["Fac"], mix.inputs[2])
        _bump(nb, p, mix.outputs[0], 0.25, 0.004)
        # slight colour variation from folds (cavities darker)
        cm = nb.n("ShaderNodeMix", (-350, 150), _data_type='RGBA', _blend_type='MULTIPLY')
        cm.inputs["Factor"].default_value = 0.35
        cm.inputs[6].default_value = color
        r = nb.n("ShaderNodeValToRGB", (-600, 250))
        r.color_ramp.elements[0].color = (0.55, 0.55, 0.55, 1)
        r.color_ramp.elements[1].color = (1, 1, 1, 1)
        nb.l(folds.outputs["Fac"], r.inputs[0])
        nb.l(r.outputs[0], cm.inputs[7])
        nb.l(cm.outputs[2], p.inputs["Base Color"])
    return m


def hoodie():
    return fabric("MAT_Hoodie", (0.72, 0.36, 0.045, 1), scale=220, rough=0.9, fold_strength=0.5, sheen=0.12, mode="rest")


def denim():
    return fabric("MAT_Denim", (0.035, 0.05, 0.095, 1), scale=300, rough=0.8, fold_strength=0.3, sheen=0.04, mode="rest")


def hair():
    m, nb = _new("MAT_Hair")
    if nb:
        p, _ = _principled(nb, (0.034, 0.021, 0.014, 1), 0.40)
        p.inputs["Specular IOR Level"].default_value = 0.45
        co = coords(nb, "rest", (-1100, -200))
        w = nb.n("ShaderNodeTexNoise", (-650, -200), Scale=90.0, Detail=3.0)
        mp = nb.n("ShaderNodeMapping", (-850, -200))
        mp.inputs["Scale"].default_value = (1.0, 0.12, 0.55)      # strands comb front to back
        nb.l(co, mp.inputs[0])
        nb.l(mp.outputs[0], w.inputs["Vector"])
        _bump(nb, p, w.outputs["Fac"], 0.22, 0.002)
    return m


def eye():
    """Procedural eyeball: sclera / iris / pupil from object-space forward axis (-Y)."""
    m, nb = _new("MAT_Eye")
    if nb:
        p, _ = _principled(nb, (0.9, 0.9, 0.9, 1), 0.08)
        p.inputs["Coat Weight"].default_value = 1.0
        p.inputs["Coat Roughness"].default_value = 0.02
        co = coords(nb, "rest", (-1100, 0))
        nrm = nb.n("ShaderNodeVectorMath", (-900, 0), _operation='NORMALIZE')
        nb.l(co, nrm.inputs[0])
        dot = nb.n("ShaderNodeVectorMath", (-700, 0), _operation='DOT_PRODUCT')
        dot.inputs[1].default_value = (0, -1, 0)
        nb.l(nrm.outputs[0], dot.inputs[0])
        ramp = nb.n("ShaderNodeValToRGB", (-450, 0))
        cr = ramp.color_ramp
        cr.interpolation = 'LINEAR'
        cr.elements[0].position = 0.0
        cr.elements[0].color = (0.62, 0.60, 0.57, 1)      # sclera
        cr.elements[1].position = 0.70
        cr.elements[1].color = (0.55, 0.53, 0.50, 1)
        e = cr.elements.new(0.715); e.color = (0.03, 0.018, 0.01, 1)   # limbal ring
        e = cr.elements.new(0.74); e.color = (0.12, 0.06, 0.025, 1)    # iris outer
        e = cr.elements.new(0.88); e.color = (0.26, 0.14, 0.05, 1)     # iris inner
        e = cr.elements.new(0.895); e.color = (0.005, 0.005, 0.005, 1) # pupil
        e = cr.elements.new(1.0); e.color = (0.0, 0.0, 0.0, 1)
        nb.l(dot.outputs["Value"], ramp.inputs[0])
        nb.l(ramp.outputs[0], p.inputs["Base Color"])
    return m


def mouth():
    """Three material slots for the shape-keyed mouth: lip line, teeth, interior."""
    return [simple("MAT_MouthLine", (0.12, 0.03, 0.03, 1), 0.9),
            simple("MAT_Teeth", (0.80, 0.76, 0.68, 1), 0.5),
            simple("MAT_MouthInside", (0.06, 0.01, 0.012, 1), 0.95, **{"Specular IOR Level": 0.1})]


def wood(name="MAT_Wood", base=(0.32, 0.18, 0.09, 1), dark=(0.16, 0.08, 0.04, 1), scale=3.0, rough=0.45):
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, base, rough)
        tc = nb.n("ShaderNodeTexCoord", (-1200, 0))
        mp = nb.n("ShaderNodeMapping", (-1000, 0))
        mp.inputs["Scale"].default_value = (scale * 0.25, scale * 4.0, scale)
        nb.l(tc.outputs["Object"], mp.inputs[0])
        w = nb.n("ShaderNodeTexWave", (-800, 0), Scale=2.0, Distortion=8.0, Detail=3.0)
        w.bands_direction = 'X'
        nb.l(mp.outputs[0], w.inputs[0])
        r = nb.n("ShaderNodeValToRGB", (-500, 0))
        r.color_ramp.elements[0].color = dark
        r.color_ramp.elements[1].color = base
        nb.l(w.outputs["Fac"], r.inputs[0])
        nb.l(r.outputs[0], p.inputs["Base Color"])
        n = nb.n("ShaderNodeTexNoise", (-800, -300), Scale=30.0, Detail=8.0)
        nb.l(tc.outputs["Object"], n.inputs[0])
        rr = nb.n("ShaderNodeMapRange", (-500, -300))
        rr.inputs["To Min"].default_value = rough - 0.12
        rr.inputs["To Max"].default_value = rough + 0.15
        nb.l(n.outputs["Fac"], rr.inputs[0])
        nb.l(rr.outputs[0], p.inputs["Roughness"])
        _bump(nb, p, w.outputs["Fac"], 0.05, 0.002)
    return m


def floor_planks():
    m, nb = _new("MAT_FloorPlanks")
    if nb:
        p, _ = _principled(nb, (0.25, 0.14, 0.07, 1), 0.5)
        tc = nb.n("ShaderNodeTexCoord", (-1300, 0))
        brick = nb.n("ShaderNodeTexBrick", (-1000, 0), Scale=1.0, Mortar_Size=0.004,
                     Bias=0.0, Brick_Width=1.4, Row_Height=0.16)
        brick.offset = 0.37
        brick.squash = 1.0
        brick.inputs["Color1"].default_value = (0.30, 0.17, 0.08, 1)
        brick.inputs["Color2"].default_value = (0.22, 0.12, 0.06, 1)
        brick.inputs["Mortar"].default_value = (0.05, 0.03, 0.02, 1)
        nb.l(tc.outputs["Object"], brick.inputs["Vector"])
        w = nb.n("ShaderNodeTexWave", (-1000, -300), Scale=3.0, Distortion=10.0, Detail=4.0)
        w.bands_direction = 'X'
        nb.l(tc.outputs["Object"], w.inputs[0])
        mix = nb.n("ShaderNodeMix", (-600, 0), _data_type='RGBA', _blend_type='MULTIPLY')
        mix.inputs["Factor"].default_value = 0.4
        nb.l(brick.outputs["Color"], mix.inputs[6])
        r = nb.n("ShaderNodeValToRGB", (-750, -300))
        r.color_ramp.elements[0].color = (0.6, 0.6, 0.6, 1)
        nb.l(w.outputs["Fac"], r.inputs[0])
        nb.l(r.outputs[0], mix.inputs[7])
        nb.l(mix.outputs[2], p.inputs["Base Color"])
        _bump(nb, p, brick.outputs["Fac"], 0.3, 0.002)
    return m


def wall_paint(name="MAT_Wall", color=(0.55, 0.53, 0.50, 1)):
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, color, 0.85)
        tc = nb.n("ShaderNodeTexCoord", (-900, 0))
        n = nb.n("ShaderNodeTexNoise", (-700, 0), Scale=40.0, Detail=6.0)
        nb.l(tc.outputs["Object"], n.inputs[0])
        _bump(nb, p, n.outputs["Fac"], 0.06, 0.002)
        n2 = nb.n("ShaderNodeTexNoise", (-700, 250), Scale=1.5, Detail=2.0)
        nb.l(tc.outputs["Object"], n2.inputs[0])
        r = nb.n("ShaderNodeValToRGB", (-450, 250))
        r.color_ramp.elements[0].color = tuple(c * 0.85 for c in color[:3]) + (1,)
        r.color_ramp.elements[1].color = color
        nb.l(n2.outputs["Fac"], r.inputs[0])
        nb.l(r.outputs[0], p.inputs["Base Color"])
    return m


def emission(name, color, strength=5.0):
    m, nb = _new(name)
    if nb:
        e = nb.n("ShaderNodeEmission", (0, 0))
        e.inputs["Color"].default_value = color
        e.inputs["Strength"].default_value = strength
        out = nb.n("ShaderNodeOutputMaterial", (300, 0))
        nb.l(e.outputs[0], out.inputs[0])
    return m


def random_color_material(name, colors, rough=0.6, attr=None):
    """Per-object colour picked by Object Info > Random (books, mugs, crowd...)."""
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, colors[0], rough)
        oi = nb.n("ShaderNodeObjectInfo", (-700, 0))
        ramp = nb.n("ShaderNodeValToRGB", (-450, 0))
        cr = ramp.color_ramp
        cr.interpolation = 'CONSTANT'
        cr.elements[0].color = colors[0]
        cr.elements[1].position = 1.0
        cr.elements[1].color = colors[-1]
        for i, c in enumerate(colors[1:-1], start=1):
            e = cr.elements.new(i / len(colors))
            e.color = c
        nb.l(oi.outputs["Random"], ramp.inputs[0])
        nb.l(ramp.outputs[0], p.inputs["Base Color"])
    return m


def image_emission(name, filepath, strength=1.0, sequence=None, extension='CLIP',
                   with_bsdf=True, gloss=0.15):
    """Screen material: image (or image sequence) as emission + glossy glass on top.

    sequence = dict(first=<film frame of first file>, count=<n files>) holds
    the first/last image outside the range.
    """
    m, nb = _new(name)
    if nb:
        img = bpy.data.images.load(filepath, check_existing=True)
        tc = nb.n("ShaderNodeTexCoord", (-900, 0))
        tex = nb.n("ShaderNodeTexImage", (-650, 0))
        tex.image = img
        tex.extension = extension
        tex.interpolation = 'Cubic'
        nb.l(tc.outputs["UV"], tex.inputs[0])
        if sequence:
            img.source = 'SEQUENCE'
            iu = tex.image_user
            iu.frame_start = sequence["first"]
            iu.frame_offset = sequence["first"] - 1
            iu.frame_duration = sequence["count"]
            iu.use_auto_refresh = True
            iu.use_cyclic = False
        em = nb.n("ShaderNodeEmission", (-300, 100))
        em.inputs["Strength"].default_value = strength
        nb.l(tex.outputs["Color"], em.inputs["Color"])
        out = nb.n("ShaderNodeOutputMaterial", (300, 0))
        if with_bsdf:
            g = nb.n("ShaderNodeBsdfPrincipled", (-300, -200))
            g.inputs["Base Color"].default_value = (0, 0, 0, 1)
            g.inputs["Roughness"].default_value = gloss
            add = nb.n("ShaderNodeAddShader", (50, 0))
            nb.l(em.outputs[0], add.inputs[0])
            nb.l(g.outputs[0], add.inputs[1])
            nb.l(add.outputs[0], out.inputs[0])
        else:
            nb.l(em.outputs[0], out.inputs[0])
        m["strength_socket"] = em.name
    return m


def glass_lens():
    m, nb = _new("MAT_Lens")
    if nb:
        p, _ = _principled(nb, (0.9, 0.95, 1.0, 1), 0.04)
        p.inputs["Alpha"].default_value = 0.03
        p.inputs["Specular IOR Level"].default_value = 0.22
        m.surface_render_method = 'BLENDED'
        m.use_backface_culling = False
    return m


def metal(name="MAT_Steel", color=(0.55, 0.56, 0.58, 1), rough=0.35, brushed=True):
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, color, rough, 1.0)
        if brushed:
            tc = nb.n("ShaderNodeTexCoord", (-900, 0))
            mp = nb.n("ShaderNodeMapping", (-700, 0))
            mp.inputs["Scale"].default_value = (300, 3, 3)
            nb.l(tc.outputs["Object"], mp.inputs[0])
            n = nb.n("ShaderNodeTexNoise", (-500, 0), Scale=4.0, Detail=4.0)
            nb.l(mp.outputs[0], n.inputs[0])
            rr = nb.n("ShaderNodeMapRange", (-300, 0))
            rr.inputs["To Min"].default_value = rough * 0.7
            rr.inputs["To Max"].default_value = rough * 1.3
            nb.l(n.outputs["Fac"], rr.inputs[0])
            nb.l(rr.outputs[0], p.inputs["Roughness"])
    return m


def concrete(name="MAT_Concrete", color=(0.12, 0.12, 0.125, 1)):
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, color, 0.8)
        tc = nb.n("ShaderNodeTexCoord", (-900, 0))
        n = nb.n("ShaderNodeTexNoise", (-700, 0), Scale=0.15, Detail=8.0, Roughness=0.6)
        nb.l(tc.outputs["Object"], n.inputs[0])
        r = nb.n("ShaderNodeValToRGB", (-450, 0))
        r.color_ramp.elements[0].color = tuple(c * 0.6 for c in color[:3]) + (1,)
        r.color_ramp.elements[1].color = tuple(min(1, c * 1.4) for c in color[:3]) + (1,)
        nb.l(n.outputs["Fac"], r.inputs[0])
        nb.l(r.outputs[0], p.inputs["Base Color"])
        rr = nb.n("ShaderNodeMapRange", (-450, -250))
        rr.inputs["To Min"].default_value = 0.35   # wet-ish polished patches catch the glow
        rr.inputs["To Max"].default_value = 0.85
        nb.l(n.outputs["Fac"], rr.inputs[0])
        nb.l(rr.outputs[0], p.inputs["Roughness"])
    return m


def belt(name="MAT_Belt"):
    """Ribbed rubber belt. Mapping offset is driven by the speed controller."""
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, (0.035, 0.035, 0.04, 1), 0.6)
        tc = nb.n("ShaderNodeTexCoord", (-1100, 0))
        mp = nb.n("ShaderNodeMapping", (-900, 0))
        mp.name = "BeltScroll"
        nb.l(tc.outputs["UV"], mp.inputs[0])
        sep = nb.n("ShaderNodeSeparateXYZ", (-700, 0))
        nb.l(mp.outputs[0], sep.inputs[0])
        mul = nb.n("ShaderNodeMath", (-550, 0), _operation='MULTIPLY')
        mul.inputs[1].default_value = 2.5          # ribs per metre
        nb.l(sep.outputs["X"], mul.inputs[0])
        fr = nb.n("ShaderNodeMath", (-400, 0), _operation='FRACT')
        nb.l(mul.outputs[0], fr.inputs[0])
        rib = nb.n("ShaderNodeMath", (-250, 0), _operation='GREATER_THAN')
        rib.inputs[1].default_value = 0.82
        nb.l(fr.outputs[0], rib.inputs[0])
        _bump(nb, p, rib.outputs[0], 0.6, 0.01)
        cm = nb.n("ShaderNodeMix", (-150, 200), _data_type='RGBA')
        cm.inputs[6].default_value = (0.04, 0.04, 0.045, 1)
        cm.inputs[7].default_value = (0.10, 0.09, 0.07, 1)   # worn rib tops
        nb.l(rib.outputs[0], cm.inputs["Factor"])
        nb.l(cm.outputs[2], p.inputs["Base Color"])
    return m


def hazard_stripes(name="MAT_Hazard"):
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, (0.6, 0.45, 0.02, 1), 0.6)
        tc = nb.n("ShaderNodeTexCoord", (-900, 0))
        w = nb.n("ShaderNodeTexWave", (-700, 0), Scale=4.0, Distortion=0.0)
        w.bands_direction = 'DIAGONAL'
        w.wave_profile = 'SAW'
        nb.l(tc.outputs["Object"], w.inputs[0])
        g = nb.n("ShaderNodeMath", (-500, 0), _operation='GREATER_THAN')
        g.inputs[1].default_value = 0.5
        nb.l(w.outputs["Fac"], g.inputs[0])
        cm = nb.n("ShaderNodeMix", (-300, 0), _data_type='RGBA')
        cm.inputs[6].default_value = (0.55, 0.38, 0.02, 1)
        cm.inputs[7].default_value = (0.02, 0.02, 0.02, 1)
        nb.l(g.outputs[0], cm.inputs["Factor"])
        nb.l(cm.outputs[2], p.inputs["Base Color"])
    return m


def city_window():
    """Fake night city behind the window: a backlit panel (part of the joke).

    Two layers of buildings with fine lit windows and a sky gradient. The 'Dawn'
    value (0..1) is keyed from the racing clock.
    """
    m, nb = _new("MAT_CityBacklight")
    if not nb:
        return m
    tc = nb.n("ShaderNodeTexCoord", (-1800, 0))
    sep = nb.n("ShaderNodeSeparateXYZ", (-1600, 0))
    nb.l(tc.outputs["UV"], sep.inputs[0])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    dawn = nb.n("ShaderNodeValue", (-1600, 600))
    dawn.name = "Dawn"
    dawn.outputs[0].default_value = 0.0

    def math(op, a, b=None):
        node = nb.n("ShaderNodeMath", (0, 0), _operation=op)
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                node.inputs[i].default_value = x
            else:
                nb.l(x, node.inputs[i])
        return node.outputs[0]

    def rand1(x, seed):
        wn = nb.n("ShaderNodeTexWhiteNoise", (0, 0))
        wn.noise_dimensions = '2D'
        cmb = nb.n("ShaderNodeCombineXYZ", (0, 0))
        nb.l(x, cmb.inputs[0])
        cmb.inputs[1].default_value = seed
        nb.l(cmb.outputs[0], wn.inputs["Vector"])
        return wn.outputs["Value"]

    def layer(cols, hmin, hmax, wx, wy, seed, on_thresh):
        col = math('FLOOR', math('MULTIPLY', u, cols))
        h = math('ADD', math('MULTIPLY', rand1(col, seed), hmax - hmin), hmin)
        inside = math('LESS_THAN', v, h)
        fu = math('FRACT', math('MULTIPLY', u, cols * wx))
        fv = math('FRACT', math('MULTIPLY', v, wy))
        win = math('MULTIPLY', math('LESS_THAN', fu, 0.55), math('LESS_THAN', fv, 0.5))
        wid = math('ADD', math('FLOOR', math('MULTIPLY', u, cols * wx)),
                   math('MULTIPLY', math('FLOOR', math('MULTIPLY', v, wy)), 131.0))
        lit = math('GREATER_THAN', rand1(wid, seed + 7), on_thresh)
        margin = math('LESS_THAN', v, math('SUBTRACT', h, 0.02))
        return inside, math('MULTIPLY', math('MULTIPLY', math('MULTIPLY', win, lit), inside), margin), rand1(wid, seed + 13)

    far_in, far_win, far_r = layer(14, 0.30, 0.62, 5, 70, 3.0, 0.62)
    near_in, near_win, near_r = layer(6, 0.18, 0.48, 6, 46, 9.0, 0.70)
    sky_n = nb.n("ShaderNodeValToRGB", (-300, 600))
    sky_n.color_ramp.elements[0].color = (0.012, 0.018, 0.045, 1)
    sky_n.color_ramp.elements[1].color = (0.002, 0.003, 0.010, 1)
    nb.l(v, sky_n.inputs[0])
    sky_d = nb.n("ShaderNodeValToRGB", (-300, 400))
    sky_d.color_ramp.elements[0].color = (0.55, 0.30, 0.20, 1)
    sky_d.color_ramp.elements[1].color = (0.10, 0.16, 0.32, 1)
    nb.l(v, sky_d.inputs[0])
    sky = nb.n("ShaderNodeMix", (-50, 500), _data_type='RGBA')
    nb.l(dawn.outputs[0], sky.inputs["Factor"])
    nb.l(sky_n.outputs[0], sky.inputs[6])
    nb.l(sky_d.outputs[0], sky.inputs[7])
    c = sky.outputs[2]

    def mixc(base, fac, color):
        mx = nb.n("ShaderNodeMix", (0, 0), _data_type='RGBA')
        nb.l(fac, mx.inputs["Factor"])
        nb.l(base, mx.inputs[6])
        if isinstance(color, tuple):
            mx.inputs[7].default_value = color
        else:
            nb.l(color, mx.inputs[7])
        return mx.outputs[2]

    c = mixc(c, far_in, (0.010, 0.012, 0.022, 1))
    warm = nb.n("ShaderNodeValToRGB", (150, 100))
    warm.color_ramp.elements[0].color = (0.35, 0.19, 0.08, 1)
    warm.color_ramp.elements[1].color = (0.26, 0.30, 0.35, 1)
    nb.l(far_r, warm.inputs[0])
    c = mixc(c, far_win, warm.outputs[0])
    c = mixc(c, near_in, (0.003, 0.004, 0.008, 1))
    warm2 = nb.n("ShaderNodeValToRGB", (600, 100))
    warm2.color_ramp.elements[0].color = (1.0, 0.62, 0.30, 1)
    warm2.color_ramp.elements[1].color = (1.0, 0.85, 0.6, 1)
    nb.l(near_r, warm2.inputs[0])
    c = mixc(c, near_win, warm2.outputs[0])
    em = nb.n("ShaderNodeEmission", (1000, 300))
    em.inputs["Strength"].default_value = 1.4
    nb.l(c, em.inputs["Color"])
    out = nb.n("ShaderNodeOutputMaterial", (1200, 300))
    nb.l(em.outputs[0], out.inputs[0])
    return m


def paper(name="MAT_Paper", color=(0.82, 0.78, 0.68, 1)):
    m, nb = _new(name)
    if nb:
        p, _ = _principled(nb, color, 0.75)
        p.inputs["Subsurface Weight"].default_value = 0.1
        tc = nb.n("ShaderNodeTexCoord", (-900, 0))
        n = nb.n("ShaderNodeTexNoise", (-700, 0), Scale=200.0, Detail=4.0)
        nb.l(tc.outputs["Object"], n.inputs[0])
        _bump(nb, p, n.outputs["Fac"], 0.05, 0.001)
    return m


def roadmap_paper():
    """The physical roadmap scroll: printed rows of checkboxes along its length."""
    m, nb = _new("MAT_RoadmapPaper")
    if nb:
        p, _ = _principled(nb, (0.85, 0.83, 0.78, 1), 0.7)
        tc = nb.n("ShaderNodeTexCoord", (-1200, 0))
        sep = nb.n("ShaderNodeSeparateXYZ", (-1000, 0))
        nb.l(tc.outputs["UV"], sep.inputs[0])
        # rows along U (length in metres), columns across V
        rows = nb.n("ShaderNodeMath", (-800, 100), _operation='MULTIPLY')
        rows.inputs[1].default_value = 18.0
        nb.l(sep.outputs["X"], rows.inputs[0])
        fr = nb.n("ShaderNodeMath", (-650, 100), _operation='FRACT')
        nb.l(rows.outputs[0], fr.inputs[0])
        line = nb.n("ShaderNodeMath", (-500, 100), _operation='LESS_THAN')
        line.inputs[1].default_value = 0.35
        nb.l(fr.outputs[0], line.inputs[0])
        colmask = nb.n("ShaderNodeMapRange", (-650, -150))
        colmask.inputs["From Min"].default_value = 0.18
        colmask.inputs["From Max"].default_value = 0.2
        nb.l(sep.outputs["Y"], colmask.inputs[0])
        # text "lines" of varying length
        wn = nb.n("ShaderNodeTexWhiteNoise", (-650, -350))
        wn.noise_dimensions = '1D'
        fl = nb.n("ShaderNodeMath", (-800, -350), _operation='FLOOR')
        nb.l(rows.outputs[0], fl.inputs[0])
        nb.l(fl.outputs[0], wn.inputs["W"])
        lenm = nb.n("ShaderNodeMapRange", (-500, -350))
        lenm.inputs["To Min"].default_value = 0.4
        lenm.inputs["To Max"].default_value = 0.92
        nb.l(wn.outputs["Value"], lenm.inputs[0])
        shorter = nb.n("ShaderNodeMath", (-350, -250), _operation='LESS_THAN')
        nb.l(sep.outputs["Y"], shorter.inputs[0])
        nb.l(lenm.outputs[0], shorter.inputs[1])
        txt = nb.n("ShaderNodeMath", (-200, -100), _operation='MULTIPLY')
        nb.l(line.outputs[0], txt.inputs[0])
        nb.l(shorter.outputs[0], txt.inputs[1])
        txt2 = nb.n("ShaderNodeMath", (-100, -100), _operation='MULTIPLY')
        nb.l(txt.outputs[0], txt2.inputs[0])
        nb.l(colmask.outputs[0], txt2.inputs[1])
        # checkbox squares near the left edge
        box = nb.n("ShaderNodeMapRange", (-650, -550))
        box.inputs["From Min"].default_value = 0.06
        box.inputs["From Max"].default_value = 0.065
        nb.l(sep.outputs["Y"], box.inputs[0])
        box2 = nb.n("ShaderNodeMapRange", (-650, -750))
        box2.inputs["From Min"].default_value = 0.13
        box2.inputs["From Max"].default_value = 0.125
        nb.l(sep.outputs["Y"], box2.inputs[0])
        bx = nb.n("ShaderNodeMath", (-450, -650), _operation='MULTIPLY')
        nb.l(box.outputs[0], bx.inputs[0])
        nb.l(box2.outputs[0], bx.inputs[1])
        bxl = nb.n("ShaderNodeMath", (-300, -650), _operation='MULTIPLY')
        nb.l(bx.outputs[0], bxl.inputs[0])
        nb.l(line.outputs[0], bxl.inputs[1])
        ink = nb.n("ShaderNodeMath", (0, -300), _operation='MAXIMUM')
        nb.l(txt2.outputs[0], ink.inputs[0])
        nb.l(bxl.outputs[0], ink.inputs[1])
        cm = nb.n("ShaderNodeMix", (150, 100), _data_type='RGBA')
        cm.inputs[6].default_value = (0.85, 0.83, 0.78, 1)
        cm.inputs[7].default_value = (0.08, 0.08, 0.1, 1)
        nb.l(ink.outputs[0], cm.inputs["Factor"])
        nb.l(cm.outputs[2], p.inputs["Base Color"])
        p.location = (350, 0)
        nb.nodes["Material Output"].location = (650, 0)
    return m
