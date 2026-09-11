/* AEFrameTools: ES3 helpers. Loading this file defines functions only.
   No project is opened, saved, rendered or modified until a caller invokes a helper.
   Host helpers receive the project/comp/property explicitly. No effects are assumed. */
var AEFrameTools = (function () {
    function requireValue(condition, message) {
        if (!condition) throw new Error('AEFrameTools: ' + message);
    }
    function finite(value) {
        return typeof value === 'number' && isFinite(value);
    }
    function integer(value) {
        return finite(value) && Math.floor(value) === value;
    }
    function array(value) {
        return Object.prototype.toString.call(value) === '[object Array]';
    }
    function numberValue(value) {
        if (typeof value === 'number') {
            requireValue(finite(value), 'Key value contains a non-finite number.');
        } else if (array(value)) {
            for (var i = 0; i < value.length; i++) numberValue(value[i]);
        }
        // Shape, TextDocument and other native AE value objects pass through.
    }
    function frameToTime(frame, fps) {
        requireValue(integer(frame), 'Frame must be an integer.');
        requireValue(finite(fps) && fps > 0, 'FPS must be positive.');
        return frame / fps;
    }
    function vectorText(value) {
        requireValue(array(value), 'vectorText expects an array.');
        var parts = [];
        for (var i = 0; i < value.length; i++) parts.push(String(value[i]));
        return parts.join(',');
    }
    function checkProperty(property) {
        requireValue(property && typeof property.numKeys === 'number', 'Expected a leaf AE property.');
        requireValue(property.matchName !== 'ADBE Time Remapping',
            'Time Remapping is not supported: removing its last key can disable remapping. Preserve endpoint keys and write with setValueAtTime, or use a dedicated remap rebuild.');
        requireValue(!property.expressionEnabled, 'Disable or deliberately replace the expression before writing keys.');
        requireValue(!property.isSeparationLeader || !property.dimensionsSeparated,
            'Position is separated; pass one dimension follower at a time.');
    }
    function basicValueShape(property) {
        var current;
        try { current = property.value; } catch (e) { return null; }
        if (typeof current === 'number') return { kind: 'number' };
        if (typeof current === 'string') return { kind: 'string' };
        if (array(current)) {
            for (var i = 0; i < current.length; i++) {
                if (typeof current[i] !== 'number') return null;
            }
            return { kind: 'numericArray', length: current.length };
        }
        // Missing/unreadable values and native objects have no inferred schema.
        return null;
    }
    function checkBasicValueShape(value, shape) {
        if (!shape) return;
        if (shape.kind === 'number' || shape.kind === 'string') {
            requireValue(typeof value === shape.kind, 'Key value must match the current scalar type: ' + shape.kind + '.');
        } else if (shape.kind === 'numericArray') {
            requireValue(array(value) && value.length === shape.length,
                'Key vector must match the current vector length: ' + shape.length + '.');
            for (var i = 0; i < value.length; i++) {
                requireValue(typeof value[i] === 'number', 'Every vector component must be numeric.');
            }
        }
    }
    function clearKeys(property) {
        checkProperty(property);
        var removed = property.numKeys;
        while (property.numKeys > 0) property.removeKey(property.numKeys);
        return removed;
    }
    function setKeys(property, frameValues, fps, interpolation) {
        checkProperty(property);
        requireValue(array(frameValues), 'Keys must be an array of [frame, value] pairs.');
        frameToTime(0, fps);
        requireValue(frameValues.length === 0 || property.canVaryOverTime !== false, 'Property cannot be animated.');
        var previous = null, times = [], values = [], valueShape = basicValueShape(property);
        for (var i = 0; i < frameValues.length; i++) {
            var pair = frameValues[i];
            requireValue(array(pair) && pair.length === 2, 'Each key must contain exactly a frame and a value.');
            var frame = pair[0];
            requireValue(integer(frame), 'Key frames must be integers.');
            requireValue(previous === null || frame > previous, 'Key frames must be strictly increasing, with no duplicates.');
            requireValue(typeof pair[1] !== 'undefined' && pair[1] !== null, 'Key value is missing.');
            numberValue(pair[1]);
            checkBasicValueShape(pair[1], valueShape);
            times.push(frameToTime(frame, fps)); values.push(pair[1]); previous = frame;
        }
        if (typeof interpolation === 'undefined' && typeof KeyframeInterpolationType !== 'undefined') {
            interpolation = KeyframeInterpolationType.LINEAR;
        }
        if (typeof interpolation !== 'undefined' && property.isInterpolationTypeValid) {
            requireValue(property.isInterpolationTypeValid(interpolation), 'Interpolation is unsupported by this property.');
        }
        // A readable current scalar/vector constrains basic type and vector length.
        // Native object types, host ranges and unavailable values need caller checks.
        // Validation precedes deletion. A native setter failure is not transactional;
        // the caller must avoid saving and reload its candidate if a host write fails.
        clearKeys(property);
        for (var i = 0; i < times.length; i++) property.setValueAtTime(times[i], values[i]);
        if (typeof interpolation !== 'undefined') {
            for (var i = 1; i <= property.numKeys; i++) property.setInterpolationTypeAtKey(i, interpolation, interpolation);
        }
        requireValue(property.numKeys === frameValues.length, 'Unexpected final key count.');
        return property;
    }
    function fitScale(sourceWidth, sourceHeight, width, height, mode) {
        requireValue(finite(sourceWidth) && sourceWidth > 0 && finite(sourceHeight) && sourceHeight > 0, 'Source dimensions must be positive.');
        requireValue(finite(width) && width > 0 && finite(height) && height > 0, 'Box dimensions must be positive.');
        if (typeof mode === 'undefined') mode = 'cover';
        requireValue(mode === 'cover' || mode === 'contain', 'Fit mode must be cover or contain.');
        var x = width / sourceWidth, y = height / sourceHeight;
        return 100 * (mode === 'cover' ? Math.max(x, y) : Math.min(x, y));
    }
    function point(value, label) {
        requireValue(array(value) && value.length === 2 && finite(value[0]) && finite(value[1]), label + ' must contain two finite numbers.');
        return [value[0], value[1]];
    }
    function portraitPlacement(sourceWidth, sourceHeight, width, height, focus, focusAt, zoom) {
        var baseScale = fitScale(sourceWidth, sourceHeight, width, height, 'cover');
        if (typeof zoom === 'undefined') zoom = 1;
        requireValue(finite(zoom) && zoom >= 1, 'Portrait zoom must be at least 1.');
        focus = point(focus || [sourceWidth / 2, sourceHeight / 2], 'Focus');
        focusAt = point(focusAt || [width / 2, height / 2], 'Focus destination');
        requireValue(focus[0] >= 0 && focus[0] <= sourceWidth && focus[1] >= 0 && focus[1] <= sourceHeight, 'Focus is outside source bounds.');
        var scale = baseScale * zoom, ratio = scale / 100;
        var minX = width - (sourceWidth - focus[0]) * ratio, maxX = focus[0] * ratio;
        var minY = height - (sourceHeight - focus[1]) * ratio, maxY = focus[1] * ratio;
        return {
            anchor: focus,
            position: [Math.max(minX, Math.min(maxX, focusAt[0])), Math.max(minY, Math.min(maxY, focusAt[1]))],
            scale: [scale, scale]
        };
    }
    function transform(layer, matchName) {
        var group = layer.property('ADBE Transform Group');
        var property = group && group.property(matchName);
        requireValue(!!property, 'Missing transform property: ' + matchName);
        return property;
    }
    function rectangleShape(left, top, right, bottom) {
        var shape = new Shape();
        shape.vertices = [[left, top], [right, top], [right, bottom], [left, bottom]];
        shape.inTangents = [[0, 0], [0, 0], [0, 0], [0, 0]];
        shape.outTangents = [[0, 0], [0, 0], [0, 0], [0, 0]];
        shape.closed = true;
        return shape;
    }
    function addFixedPortraitPanel(project, parentComp, source, options) {
        var o = options || {};
        requireValue(project && project.items && parentComp && parentComp.layers && source, 'Supply a project, parent comp and source explicitly.');
        requireValue(typeof o.name === 'string' && o.name.length > 0, 'Panel name is required.');
        requireValue(integer(o.width) && o.width >= 4 && integer(o.height) && o.height >= 4, 'Panel dimensions must be integers of at least 4 pixels.');
        var fps = parentComp.frameRate;
        var frames = typeof o.durationFrames === 'undefined' ? Math.round(parentComp.duration * fps) : o.durationFrames;
        requireValue(integer(frames) && frames > 0, 'Panel duration must contain positive integer frames.');
        var duration = frameToTime(frames, fps);
        requireValue(Math.abs(parentComp.pixelAspect - 1) < 0.0001 && Math.abs(source.pixelAspect - 1) < 0.0001,
            'This panel helper requires square pixels; normalize non-square media first.');
        var center = point(o.center || [parentComp.width / 2, parentComp.height / 2], 'Panel center');
        var placement = portraitPlacement(source.width, source.height, o.width, o.height, o.focus, o.focusAt, o.zoom);
        var borderWidth = typeof o.borderWidth === 'undefined' ? 2 : o.borderWidth;
        requireValue(finite(borderWidth) && borderWidth >= 0 && borderWidth < Math.min(o.width, o.height), 'Invalid border width.');
        var color = o.borderColor || [1, 1, 1];
        requireValue(array(color) && color.length === 3, 'Border color must be RGB.');
        for (var k = 0; k < 3; k++) requireValue(finite(color[k]) && color[k] >= 0 && color[k] <= 1, 'RGB values must be in 0..1.');
        for (var k = 1; k <= project.numItems; k++) {
            requireValue(project.item(k).name !== o.name, 'Panel name already exists; choose a unique name.');
        }
        var panelComp = project.items.addComp(o.name, o.width, o.height, 1, duration, fps);
        var art = panelComp.layers.add(source);
        art.name = 'ART / independent internal motion';
        transform(art, 'ADBE Anchor Point').setValue(placement.anchor);
        transform(art, 'ADBE Position').setValue(placement.position);
        transform(art, 'ADBE Scale').setValue(placement.scale);
        var frame = null;
        if (borderWidth > 0) {
            frame = panelComp.layers.addShape(); frame.name = 'FRAME / fixed panel edge';
            transform(frame, 'ADBE Position').setValue([0, 0]);
            var group = frame.property('ADBE Root Vectors Group').addProperty('ADBE Vector Group');
            var contents = group.property('ADBE Vectors Group');
            var path = contents.addProperty('ADBE Vector Shape - Group');
            var inset = borderWidth / 2;
            path.property('ADBE Vector Shape').setValue(rectangleShape(inset, inset, o.width - inset, o.height - inset));
            var stroke = contents.addProperty('ADBE Vector Graphic - Stroke');
            stroke.property('ADBE Vector Stroke Color').setValue(color);
            stroke.property('ADBE Vector Stroke Width').setValue(borderWidth);
        }
        var panel = parentComp.layers.add(panelComp);
        panel.name = o.name + ' / fixed window';
        transform(panel, 'ADBE Anchor Point').setValue([o.width / 2, o.height / 2]);
        transform(panel, 'ADBE Position').setValue(center);
        var mask = panel.property('ADBE Mask Parade').addProperty('ADBE Mask Atom');
        mask.name = 'MASK / fixed rectangle';
        mask.property('ADBE Mask Shape').setValue(rectangleShape(0, 0, o.width, o.height));
        mask.property('ADBE Mask Feather').setValue([0, 0]);
        // The art can pan inside panelComp without moving the fixed edge or mask.
        return { panelComp: panelComp, panelLayer: panel, artLayer: art, frameLayer: frame, mask: mask };
    }
    return {
        version: '1.0.0',
        frameToTime: frameToTime,
        vectorText: vectorText,
        clearKeys: clearKeys,
        setKeys: setKeys,
        fitScale: fitScale,
        portraitPlacement: portraitPlacement,
        addFixedPortraitPanel: addFixedPortraitPanel
    };
})();
