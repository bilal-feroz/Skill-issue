"""Render configuration, quality presets and the compositor (fog, bloom, vignette)."""

import bpy

PRESETS = {
    #           res %, samples, motion blur, raytracing
    "draft":   dict(pct=25, samples=4, mb=False, rt=False),
    "preview": dict(pct=50, samples=12, mb=True, rt=True),
    "final":   dict(pct=100, samples=48, mb=True, rt=True),
}


def configure(scene, preset="preview", frames_dir=None):
    p = PRESETS[preset]
    r = scene.render
    r.engine = 'BLENDER_EEVEE'
    r.resolution_x, r.resolution_y = 1920, 1080
    r.resolution_percentage = p["pct"]
    r.fps = 24
    r.fps_base = 1.0
    scene.frame_start, scene.frame_end = 1, 720
    r.use_motion_blur = p["mb"]
    r.motion_blur_shutter = 0.42
    r.film_transparent = False
    r.filter_size = 1.3
    e = scene.eevee
    e.taa_render_samples = p["samples"]
    e.use_raytracing = p["rt"]
    e.ray_tracing_method = 'SCREEN'
    e.use_fast_gi = True
    e.fast_gi_method = 'GLOBAL_ILLUMINATION'
    e.use_shadows = True
    e.shadow_ray_count = 1
    e.shadow_step_count = 6
    e.use_volumetric_shadows = False
    e.clamp_surface_indirect = 10.0
    vs = scene.view_settings
    vs.view_transform = 'AgX'
    vs.look = 'AgX - Medium High Contrast'
    vs.exposure = 0.0
    vs.gamma = 1.0
    scene.display_settings.display_device = 'sRGB'
    r.image_settings.file_format = 'PNG'
    r.image_settings.color_mode = 'RGB'
    r.image_settings.color_depth = '8'
    r.image_settings.compression = 15
    r.use_file_extension = True
    if frames_dir:
        r.filepath = frames_dir.rstrip("/\\") + "/frame_"
    scene.view_layers[0].use_pass_mist = True
    return p


def compositor(scene):
    """Mist-based atmospheric fog (keyed per act), bloom, vignette."""
    ng = bpy.data.node_groups.get("COMP_SkillIssue")
    if ng:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new("COMP_SkillIssue", "CompositorNodeTree")
    scene.compositing_node_group = ng
    ng.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    N = ng.nodes
    Lk = ng.links
    rl = N.new("CompositorNodeRLayers")
    rl.location = (-900, 0)
    # fog = mix(image, fog colour, mist * FogAmount)
    amt = N.new("ShaderNodeValue")
    amt.name = "FogAmount"
    amt.label = "FogAmount (keyed)"
    amt.outputs[0].default_value = 0.0
    amt.location = (-900, -300)
    mul = N.new("ShaderNodeMath")
    mul.operation = 'MULTIPLY'
    mul.location = (-650, -200)
    Lk.new(rl.outputs["Mist"], mul.inputs[0])
    Lk.new(amt.outputs[0], mul.inputs[1])
    fog = N.new("ShaderNodeMix")
    fog.data_type = 'RGBA'
    fog.location = (-450, 0)
    Lk.new(mul.outputs[0], fog.inputs["Factor"])
    Lk.new(rl.outputs["Image"], fog.inputs[6])
    fog.inputs[7].default_value = (0.030, 0.034, 0.045, 1)
    glare = N.new("CompositorNodeGlare")
    glare.location = (-200, 0)
    try:
        glare.inputs["Type"].default_value = 'Fog Glow'
    except Exception:
        pass
    glare.inputs["Threshold"].default_value = 1.2
    glare.inputs["Strength"].default_value = 0.35
    try:
        glare.inputs["Quality"].default_value = 'Medium'
    except Exception:
        pass
    Lk.new(fog.outputs[2], glare.inputs["Image"])
    # vignette
    ell = N.new("CompositorNodeEllipseMask")
    ell.location = (-200, -350)
    ell.inputs["Size"].default_value = (0.95, 0.85)
    blur = N.new("CompositorNodeBlur")
    blur.location = (0, -350)
    try:
        blur.inputs["Size"].default_value = (400, 400)
    except Exception:
        pass
    Lk.new(ell.outputs["Mask"], blur.inputs["Image"])
    vmap = N.new("ShaderNodeMapRange")
    vmap.location = (200, -350)
    vmap.inputs["To Min"].default_value = 0.62
    vmap.inputs["To Max"].default_value = 1.0
    Lk.new(blur.outputs["Image"], vmap.inputs["Value"])
    vig = N.new("ShaderNodeMix")
    vig.data_type = 'RGBA'
    vig.blend_type = 'MULTIPLY'
    vig.location = (400, 0)
    vig.inputs["Factor"].default_value = 1.0
    Lk.new(glare.outputs["Image"], vig.inputs[6])
    Lk.new(vmap.outputs["Result"], vig.inputs[7])
    out = N.new("NodeGroupOutput")
    out.location = (650, 0)
    Lk.new(vig.outputs[2], out.inputs[0])
    return ng
