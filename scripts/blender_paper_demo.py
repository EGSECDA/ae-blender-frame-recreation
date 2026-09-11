"""Blender 4.2+ background-only curved paper / transparent-pass demonstration.

blender --background --factory-startup --python-exit-code 1 --python blender_paper_demo.py -- \
    --output-dir /absolute/output --frames 72 --render-frames 1,28,48 \
    --resolution-percent 20

Only a new background process may run this script. It refuses an existing blend
or existing demo outputs. No character art, external packages or GUI are needed.
"""
import argparse
import array
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--texture', type=Path, help='Optional front-facing paper scan; packed into blend.')
    p.add_argument('--fps', type=float, default=30.0)
    p.add_argument('--frames', type=int, default=120)
    p.add_argument('--render-frames', default='', help='Comma-separated local frames, or all; empty = build only.')
    p.add_argument('--resolution-percent', type=int, default=50)
    p.add_argument('--width', type=int, default=1920)
    p.add_argument('--height', type=int, default=1080)
    p.add_argument('--paper-count', type=int, default=15)
    p.add_argument('--absolute-start-frame', type=int, default=0, help='Zero-based timeline frame corresponding to local frame 1.')
    p.add_argument('--burst-frame', type=int, help='Local first burst frame; default 38 percent into clip.')
    p.add_argument('--center', default='0.5,0.5', help='Normalized screen x,y, top-left origin.')
    p.add_argument('--spread', type=float, default=0.32, help='Normalized post-burst midground radius.')
    p.add_argument('--protected-rect', action='append', default=[], metavar='NAME:X0,Y0,X1,Y1',
                   help='Repeatable normalized screen rectangle; audited, not silently masked.')
    p.add_argument('--strict-protection', action='store_true', help='Raise on protection intersections; use Blender --python-exit-code 1.')
    a = p.parse_args(argv)
    if not (1 <= a.fps <= 240 and a.frames >= 24 and 1 <= a.resolution_percent <= 100):
        p.error('fps must be 1..240, frames >=24, resolution-percent 1..100')
    if a.width < 64 or a.height < 64 or not 6 <= a.paper_count <= 80 or not 0.08 <= a.spread <= 0.6:
        p.error('width/height >=64; paper-count 6..80; spread 0.08..0.6')
    try:
        a.center = tuple(float(v) for v in a.center.split(','))
        assert len(a.center) == 2 and all(0 <= v <= 1 for v in a.center)
        a.regions = {}
        for item in a.protected_rect:
            name, coords = item.split(':', 1)
            r = tuple(float(v) for v in coords.split(','))
            assert name and name not in a.regions and len(r) == 4
            assert 0 <= r[0] < r[2] <= 1 and 0 <= r[1] < r[3] <= 1
            a.regions[name] = r
        a.selected = (list(range(1, a.frames + 1)) if a.render_frames == 'all' else
                      sorted(set(int(v) for v in a.render_frames.split(',') if v.strip())))
        assert all(1 <= f <= a.frames for f in a.selected)
    except (ValueError, AssertionError):
        p.error('Invalid center, protected rectangle or render-frame list.')
    a.burst_frame = a.burst_frame if a.burst_frame is not None else max(10, round(a.frames * 0.38))
    a.gather_end = max(3, round(a.burst_frame * 0.66))
    if not a.gather_end + 2 <= a.burst_frame <= a.frames - 5:
        p.error('burst-frame must leave at least two hold frames and five tail frames.')
    if a.texture:
        a.texture = a.texture.expanduser().resolve()
        if not a.texture.is_file():
            p.error('Texture file does not exist.')
    a.output_dir = a.output_dir.expanduser().resolve()
    return a


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def mix(a, b, t):
    return a + (b - a) * t


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def make_material(texture):
    m = bpy.data.materials.new('Paper / front print, fibre bump, subdued reverse')
    m.use_nodes = True
    n, links = m.node_tree.nodes, m.node_tree.links
    bs = n.get('Principled BSDF')
    bs.inputs['Roughness'].default_value = 0.76
    bs.inputs['IOR'].default_value = 1.42
    bs.inputs['Specular IOR Level'].default_value = 0.25
    bs.inputs['Sheen Weight'].default_value = 0.12
    uv = n.new('ShaderNodeTexCoord')
    ratio = 1.0 / 3.0
    if texture:
        img = bpy.data.images.load(str(texture), check_existing=False)
        ratio = img.size[0] / img.size[1]
        img.pack()
        tex = n.new('ShaderNodeTexImage')
        tex.image = img
        links.new(uv.outputs['UV'], tex.inputs['Vector'])
        color = tex.outputs['Color']
    else:
        # An editable neutral placeholder, not character art or imitation script.
        # Repeated red border and abstract dark bars make orientation readable.
        sep = n.new('ShaderNodeSeparateXYZ')
        links.new(uv.outputs['UV'], sep.inputs[0])

        def math_node(op, x, y):
            node = n.new('ShaderNodeMath'); node.operation = op
            for i, v in enumerate((x, y)):
                if isinstance(v, (int, float)): node.inputs[i].default_value = v
                else: links.new(v, node.inputs[i])
            return node.outputs[0]

        def band(socket, lo, hi):
            return math_node('MULTIPLY', math_node('GREATER_THAN', socket, lo), math_node('LESS_THAN', socket, hi))

        x, y = sep.outputs['X'], sep.outputs['Y']
        border = math_node('MAXIMUM', math_node('MAXIMUM', band(x, .065, .085), band(x, .915, .935)),
                           math_node('MAXIMUM', band(y, .055, .07), band(y, .93, .945)))
        bars = math_node('MULTIPLY', band(x, .35, .65),
                         band(math_node('PINGPONG', math_node('MULTIPLY', y, 8), 1), .4, .57))
        red = n.new('ShaderNodeMixRGB'); red.inputs[1].default_value = (.77, .69, .52, 1)
        red.inputs[2].default_value = (.42, .035, .025, 1)
        links.new(border, red.inputs[0])
        ink = n.new('ShaderNodeMixRGB'); ink.inputs[2].default_value = (.028, .022, .018, 1)
        links.new(bars, ink.inputs[0]); links.new(red.outputs[0], ink.inputs[1])
        color = ink.outputs[0]
    geo = n.new('ShaderNodeNewGeometry')
    back = n.new('ShaderNodeMath'); back.operation = 'MULTIPLY'; back.inputs[1].default_value = .22
    links.new(geo.outputs['Backfacing'], back.inputs[0])
    reverse = n.new('ShaderNodeMixRGB'); reverse.inputs[2].default_value = (.69, .62, .49, 1)
    links.new(back.outputs[0], reverse.inputs[0]); links.new(color, reverse.inputs[1])
    links.new(reverse.outputs[0], bs.inputs['Base Color'])
    stretch = n.new('ShaderNodeVectorMath'); stretch.operation = 'MULTIPLY'
    stretch.inputs[1].default_value = (38, 390, 24)
    links.new(uv.outputs['Generated'], stretch.inputs[0])
    noise = n.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 5
    noise.inputs['Detail'].default_value = 3
    links.new(stretch.outputs[0], noise.inputs['Vector'])
    bump = n.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = .13
    bump.inputs['Distance'].default_value = .002
    links.new(noise.outputs['Fac'], bump.inputs['Height']); links.new(bump.outputs[0], bs.inputs['Normal'])
    edge = bpy.data.materials.new('Paper / exposed thin fibre edge'); edge.use_nodes = True
    edge.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.72, .66, .53, 1)
    edge.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = .85
    return m, edge, ratio


def make_sheet(scene, index, height, ratio, materials):
    nx, ny, width = 8, 24, height * ratio

    def point(u, v, curl):
        x, y = u * width, v * height
        z = height * (.22 + .16 * curl) * v * v + (.45 + .32 * curl) * x * v
        z += height * .012 * math.sin((v + .5) * math.tau + index) * math.cos(u * math.pi)
        z += height * .026 * (1 + curl) * math.exp(-((v - .42) / .12) ** 2) * (.5 + u)
        return x, y, z

    vertices = [point(i / nx - .5, j / ny - .5, 0) for j in range(ny + 1) for i in range(nx + 1)]
    faces = [(k, k + 1, k + nx + 2, k + nx + 1)
             for j in range(ny) for i in range(nx) for k in [j * (nx + 1) + i]]
    mesh = bpy.data.meshes.new('Curved grid %02d' % index); mesh.from_pydata(vertices, [], faces); mesh.update()
    uv = mesh.uv_layers.new(name='Inset scan edges / 0.02 to 0.98')
    for face in mesh.polygons:
        face.use_smooth = True
        for li in face.loop_indices:
            vi = mesh.loops[li].vertex_index
            uv.data[li].uv = (.02 + .96 * (vi % (nx + 1)) / nx, .02 + .96 * (vi // (nx + 1)) / ny)
    obj = bpy.data.objects.new('Paper_%02d' % index, mesh); scene.collection.objects.link(obj)
    for mat in materials: mesh.materials.append(mat)
    obj.shape_key_add(name='Rest curve'); curl = obj.shape_key_add(name='Curl and twist')
    for j in range(ny + 1):
        for i in range(nx + 1): curl.data[j * (nx + 1) + i].co = point(i / nx - .5, j / ny - .5, 1)
    sub = obj.modifiers.new('Smooth curved paper', 'SUBSURF'); sub.levels = 1; sub.render_levels = 1
    thick = obj.modifiers.new('Thin visible rim', 'SOLIDIFY'); thick.thickness = .0012
    thick.offset = 0; thick.material_offset_rim = 1
    bevel = obj.modifiers.new('Lit edge', 'BEVEL'); bevel.width = .0005; bevel.segments = 2
    obj['motion_method'] = 'Art-directed mesh and shape-key animation, not a cloth simulation.'
    return obj, curl


def area_light(scene, name, position, target, energy, color, size):
    data = bpy.data.lights.new(name, 'AREA'); data.energy = energy; data.color = color; data.size = size
    obj = bpy.data.objects.new(name, data); scene.collection.objects.link(obj); obj.location = position
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def build(a):
    # The guard runs before clearing anything. A foreground Text Editor cannot run this.
    if not bpy.app.background or '--factory-startup' not in sys.argv or bpy.data.filepath:
        raise RuntimeError('Use a NEW process with --background --factory-startup and no input blend.')
    if bpy.app.version < (4, 2, 0): raise RuntimeError('Blender 4.2 or later is required.')
    if (a.output_dir / 'paper_demo.blend').exists() or list(a.output_dir.glob('renders/paper_*.png')):
        raise FileExistsError('Output already contains a demo. Use a new output directory; no files were replaced.')
    (a.output_dir / 'renders').mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    scene = bpy.context.scene; scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = a.width; scene.render.resolution_y = a.height
    scene.render.resolution_percentage = a.resolution_percent
    scene.render.fps = round(a.fps); scene.render.fps_base = round(a.fps) / a.fps
    scene.frame_start = 1; scene.frame_end = a.frames
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '16'; scene.render.image_settings.compression = 30
    scene.render.use_motion_blur = True; scene.render.motion_blur_shutter = .35
    scene.eevee.taa_render_samples = 32
    scene.view_settings.view_transform = 'AgX'
    scene.world = bpy.data.worlds.new('Invisible neutral environment'); scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.43, .5, .62, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .45
    data = bpy.data.cameras.new('Perspective and focus'); cam = bpy.data.objects.new('Camera', data)
    scene.collection.objects.link(cam); scene.camera = cam
    cam.location = (0, 0, 0); cam.rotation_euler = (0, 0, 0)
    data.lens = 50; data.sensor_width = 36; data.sensor_fit = 'HORIZONTAL'
    data.clip_start = .05; data.clip_end = 100
    data.dof.use_dof = True; data.dof.aperture_fstop = 1.8; data.dof.aperture_blades = 7
    area_light(scene, 'Warm soft key', (-3, 4, -1), (0, 0, -9), 1100, (1, .9, .78), 5)
    area_light(scene, 'Cool fill', (4, 1, -2), (0, 0, -9), 800, (.53, .73, 1), 5)
    area_light(scene, 'Curved rim', (1, -3, -13), (0, 0, -7), 1300, (1, .67, .43), 3)
    front, edge, ratio = make_material(a.texture)

    def screen_world(x, y, depth):
        span = depth * data.sensor_width / data.lens
        return ((x - .5) * span, (.5 - y) * span * a.height / a.width, -depth)

    papers = []
    for i in range(a.paper_count):
        near = i < 3
        angle = (-math.pi / 2, math.pi / 2, -.1)[i] if near else (i - 3) / (a.paper_count - 3) * math.tau
        rad = .11 + (i % 3) * .013
        gx, gy = a.center[0] + math.cos(angle) * rad, a.center[1] + math.sin(angle) * rad
        spread = a.spread * ((1.45, 1.45, .42)[i] if near else .7 + (i % 3) * .13)
        ex, ey = a.center[0] + math.cos(angle) * spread, a.center[1] + math.sin(angle) * spread
        d0 = 12.5 + (i % 4) * .55
        d1 = (3.4, 3.8, 4.8)[i] if near else 8.5 + (i % 4) * 1.1
        h = (.73, .79, .8)[i] if near else .38 + (i % 3) * .045
        obj, curl = make_sheet(scene, i, h, ratio, (front, edge))
        obj['depth_role'] = 'near / main in focus' if i == 2 else 'near / softer' if near else 'mid'
        r0 = (.1 * math.sin(i), .14 * math.cos(i), angle + math.pi / 2)
        r1 = (.26 * math.sin(i + 1), -.33 * math.cos(i), r0[2] + (-.65 if i % 2 else .55))
        for f in range(1, a.frames + 1):
            gather = smooth((f - 1) / (a.gather_end - 1))
            if f < a.burst_frame:
                x = a.center[0] + (gx - a.center[0]) * mix(1.5, 1, gather)
                y = a.center[1] + (gy - a.center[1]) * mix(1.5, 1, gather)
                depth, rot, cv = d0, r0, .22
            else:
                u = max(0, min(1, (f - a.burst_frame) / 3))
                x, y, depth = mix(gx, ex, u), mix(gy, ey, u), mix(d0, d1, u)
                rot = tuple(mix(r0[k], r1[k], u) for k in range(3)); cv = mix(.22, .72, u)
                if f > a.burst_frame + 3:
                    dt = (f - a.burst_frame - 3) / a.fps
                    x += math.cos(angle) * .004 * dt; y += math.sin(angle) * .003 * dt
                    depth -= .012 * dt
                    rot = tuple(rot[k] + .035 * math.sin(i + k + 1) * dt for k in range(3))
                    cv += .10 * (math.sin(dt * .65 + i) - math.sin(i))
            obj.location = screen_world(x, y, depth); obj.rotation_euler = rot; curl.value = cv
            obj.keyframe_insert('location', frame=f); obj.keyframe_insert('rotation_euler', frame=f)
            curl.keyframe_insert('value', frame=f)
        papers.append(obj)
    for f, focus in ((1, 13.1), (a.burst_frame, 13.1), (a.burst_frame + 3, 4.8), (a.frames, 4.8)):
        data.dof.focus_distance = focus; data.dof.keyframe_insert('focus_distance', frame=f)
    scene['frame_mapping'] = 'local 1 = zero-based timeline frame %d' % a.absolute_start_frame
    scene['protected_screen_rectangles'] = json.dumps(a.regions)
    return scene, papers


def audit_projection(a, scene, papers):
    rows, risky_frames = [], []
    for f in range(1, a.frames + 1):
        scene.frame_set(f); deps = bpy.context.evaluated_depsgraph_get(); items = []
        frame_risk = False
        for obj in papers:
            evaluated = obj.evaluated_get(deps); mesh = evaluated.to_mesh()
            try:
                co = [world_to_camera_view(scene, scene.camera, evaluated.matrix_world @ v.co) for v in mesh.vertices]
                box = [min(p.x for p in co), min(1 - p.y for p in co), max(p.x for p in co), max(1 - p.y for p in co)]
                hits = {name: max(0, min(box[2], r[2]) - max(box[0], r[0])) *
                              max(0, min(box[3], r[3]) - max(box[1], r[1])) for name, r in a.regions.items()}
                behind = any(p.z <= 0 for p in co)
                frame_risk |= behind or any(v > 0 for v in hits.values())
                items.append({'paper': obj.name, 'bounds_normalized': box, 'behind_camera': behind,
                              'protected_bbox_overlap_normalized_area': hits})
            finally:
                evaluated.to_mesh_clear()
        rows.append({'local_frame': f, 'absolute_frame': a.absolute_start_frame + f - 1, 'papers': items})
        if frame_risk: risky_frames.append(f)
    out = {'coverage': '%d/%d timeline frames' % (a.frames, a.frames),
           'method': 'evaluated depsgraph mesh including shape keys and modifiers; bounding boxes are conservative, not pixel alpha',
           'risky_frames': risky_frames, 'frames': rows}
    write_json(a.output_dir / 'projection_audit.json', out)
    return risky_frames


def audit_png(path, regions):
    header = path.read_bytes()[:26]
    img = bpy.data.images.load(str(path), check_existing=False)
    try:
        w, h = img.size; values = array.array('f', [0.0]) * (w * h * 4); img.pixels.foreach_get(values)
        alpha = values[3::4]
        protected = {}
        for name, r in regions.items():
            # Blender pixel buffers start at bottom-left; the CLI regions start at top-left.
            x0, x1 = max(0, math.floor(r[0] * w)), min(w, math.ceil(r[2] * w))
            y0, y1 = max(0, math.floor((1 - r[3]) * h)), min(h, math.ceil((1 - r[1]) * h))
            samples = (alpha[y * w + x] for y in range(y0, y1) for x in range(x0, x1))
            maximum = 0.0; over = 0
            for value in samples: maximum = max(maximum, value); over += value > 12 / 255
            protected[name] = {'alpha_max': maximum, 'pixels_over_12_of_255': over}
        return {'file': path.name, 'width': w, 'height': h, 'png_bit_depth': header[24], 'png_color_type': header[25],
                'alpha_min': min(alpha), 'alpha_max': max(alpha),
                'visible_pixels': sum(v > 1 / 65535 for v in alpha), 'protected_regions': protected, 'sha256': sha256(path)}
    finally:
        bpy.data.images.remove(img)


def main():
    a = parse_args(); scene, papers = build(a)
    risk = audit_projection(a, scene, papers)
    scene.frame_set(min(a.frames, a.burst_frame + 12))
    scene.render.filepath = str(a.output_dir / 'renders' / 'paper_')
    blend = a.output_dir / 'paper_demo.blend'; bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    renders = []
    for f in a.selected:
        path = a.output_dir / 'renders' / ('paper_%04d.png' % f)
        scene.frame_set(f); scene.render.filepath = str(path); bpy.ops.render.render(write_still=True)
        row = audit_png(path, a.regions); row['local_frame'] = f
        row['absolute_frame'] = a.absolute_start_frame + f - 1; renders.append(row)
        print('RENDER_AUDIT', json.dumps(row), flush=True)
    alpha_risk = [r['local_frame'] for r in renders if any(v['alpha_max'] > 0 for v in r['protected_regions'].values())]
    manifest = {'blender_version': bpy.app.version_string, 'script_sha256': sha256(Path(__file__).resolve()),
                'source': blend.name, 'source_sha256': sha256(blend),
                'fps_requested': a.fps, 'fps_effective': scene.render.fps / scene.render.fps_base, 'frames': a.frames,
                'frame_mapping': {'local_1_absolute_frame': a.absolute_start_frame,
                                  'formula': 'absolute = absolute_start_frame + local_frame - 1; local_time = (local_frame - 1) / fps'},
                'timing_local_frames': {'gather': [1, a.gather_end], 'hold': [a.gather_end + 1, a.burst_frame - 1],
                                        'burst_four_samples': [a.burst_frame, a.burst_frame + 3],
                                        'slow_drift': [a.burst_frame + 4, a.frames]},
                'rgba': '16-bit PNG, unassociated/straight alpha on disk; Blender internal buffers may be associated',
                'texture': str(a.texture) if a.texture else 'Internal procedural placeholder; no external art required',
                'motion': 'Deterministic curved mesh / shape-key animation; not a cloth simulation',
                'protected_regions': a.regions, 'projection_risky_frames': risk, 'rendered_alpha_risky_frames': alpha_risk,
                'rendered_alpha_audit_coverage': '%d/%d timeline frames' % (len(renders), a.frames),
                'all_frames_alpha_audited': len(renders) == a.frames,
                'visual_acceptance': 'Pending human/model view of rendered output and final compositing context',
                'renders': renders}
    write_json(a.output_dir / 'manifest.json', manifest)
    print('DONE', str(a.output_dir), 'projection_frames', a.frames, 'rendered_frames', len(renders), flush=True)
    if a.strict_protection and (risk or alpha_risk):
        raise RuntimeError('Protection intersection found; inspect saved audits and adjust trajectory. No masks were added.')


if __name__ == '__main__':
    main()
