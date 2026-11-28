.pragma library
/*
 * ASCII rendering for the About window, after edwardjones7/ascii-art (MIT): shapes get a 3D surface normal,
 * are lit by one light and turned into characters of a brightness ramp on a fixed character grid.
 * Characters always stay upright; only the shape under them rotates with its body.
 */

var RAMP = ".:;=+*xo%#&@"
var LIGHT = (function () {
    var l = [-0.45, -0.75, 0.9], n = Math.hypot(l[0], l[1], l[2])
    return [l[0] / n, l[1] / n, l[2] / n]
})()

// 5x7 block font
var FONT = {
    "A": [" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "B": ["#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "],
    "C": [" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "],
    "D": ["#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "],
    "E": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"],
    "F": ["#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "],
    "G": [" ### ", "#   #", "#    ", "# ###", "#   #", "#   #", " ####"],
    "H": ["#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "I": [" ### ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "],
    "J": ["  ###", "   # ", "   # ", "   # ", "   # ", "#  # ", " ##  "],
    "K": ["#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"],
    "L": ["#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"],
    "M": ["#   #", "## ##", "# # #", "# # #", "#   #", "#   #", "#   #"],
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #", "#   #", "#   #"],
    "O": [" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "P": ["#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "],
    "Q": [" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"],
    "R": ["#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"],
    "S": [" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "],
    "T": ["#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    "U": ["#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "V": ["#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "],
    "W": ["#   #", "#   #", "#   #", "# # #", "# # #", "## ##", "#   #"],
    "X": ["#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"],
    "Y": ["#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "],
    "Z": ["#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"],
    "0": [" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "],
    "1": ["  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "],
    "2": [" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"],
    "3": ["#### ", "    #", "    #", " ### ", "    #", "    #", "#### "],
    "4": ["   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "],
    "5": ["#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "],
    "6": [" ### ", "#    ", "#    ", "#### ", "#   #", "#   #", " ### "],
    "7": ["#####", "    #", "   # ", "  #  ", " #   ", " #   ", " #   "],
    "8": [" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "],
    "9": [" ### ", "#   #", "#   #", " ####", "    #", "    #", " ### "],
    ".": ["     ", "     ", "     ", "     ", "     ", " ##  ", " ##  "],
    "-": ["     ", "     ", "     ", "#####", "     ", "     ", "     "],
}
var BOX = ["#####", "#   #", "#   #", "#   #", "#   #", "#   #", "#####"]

function glyphRows(ch) {
    return FONT[String(ch).toUpperCase()] || BOX
}

// ------------------------------------------------------------------ lighting
// local normal (nx, ny, nz) of a body turned by angle a -> brightness 0..1
function light(nx, ny, nz, a) {
    var c = Math.cos(a), s = Math.sin(a)
    var wx = nx * c - ny * s, wy = nx * s + ny * c
    var d = wx * LIGHT[0] + wy * LIGHT[1] + nz * LIGHT[2]
    return Math.max(0, Math.min(1, 0.12 + 0.88 * Math.max(0, d)))
}

// signed distance to a rounded rectangle centred at the origin (negative inside) and its gradient
function roundRect(x, y, hw, hh, r) {
    var qx = Math.abs(x) - hw + r, qy = Math.abs(y) - hh + r
    var ox = Math.max(qx, 0), oy = Math.max(qy, 0)
    var d = Math.hypot(ox, oy) + Math.min(Math.max(qx, qy), 0) - r
    var gx, gy
    if (qx > 0 && qy > 0) { var l = Math.hypot(qx, qy); gx = qx / l; gy = qy / l }
    else if (qx > qy) { gx = 1; gy = 0 } else { gx = 0; gy = 1 }
    return [d, gx * Math.sign(x || 1), gy * Math.sign(y || 1)]
}

// pillow-shaped surface: flat face, rounded-off rim of width `rim`
function pillow(sd, rim) {
    var d = sd[0]
    if (d > 0) return null
    var t = Math.max(0, 1 + d / rim)          // 0 in the flat middle, 1 at the edge
    var tilt = Math.sin(t * Math.PI / 2) * 0.95
    return [sd[1] * tilt, sd[2] * tilt, Math.sqrt(1 - tilt * tilt)]
}

// ------------------------------------------------------------------ shapes (local coords, origin = body centre)
/// AirPods Pro case seen from the front: white rounded block, lid on top (35 %), seam line.
/// Open: the lid is flipped back (seen from inside, darker) and two dark pod slots show on the base's top edge.
function caseSampler(b, lidOpen) {
    var hw = b.w / 2, hh = b.h / 2, seam = -hh + b.h * 0.35
    return function (x, y) {
        if (!lidOpen) {
            var n = pillow(roundRect(x, y, hw, hh, b.h * 0.3), b.h * 0.22)
            if (!n) return -1
            if (Math.abs(y - seam) < b.h * 0.06) return 0.05              // seam (wide enough to hit a grid row)
            if (Math.abs(x) < b.w * 0.05 && Math.abs(y - seam - 5) < 3) return 0.25   // the little front dent
            return light(n[0], n[1], n[2], b.a)
        }
        // base: lower part
        if (y >= seam) {
            var bh = (hh - seam) / 2, by = y - (seam + bh)
            var nb = pillow(roundRect(x, by, hw, bh, Math.min(bh, b.h * 0.3)), b.h * 0.18)
            if (!nb) return -1
            // pod slots: two dark wells right under the top edge
            var slot = (Math.abs(Math.abs(x) - b.w * 0.2) < b.w * 0.09) && y < seam + b.h * 0.12
            return slot ? 0.02 : light(nb[0], nb[1], nb[2], b.a)
        }
        // open lid: thinner, seen from inside, sitting above the base
        var lh = b.h * 0.13, ly = y - (seam - lh - 2)
        var nl = pillow(roundRect(x, ly, hw * 0.96, lh, lh), lh * 0.8)
        if (!nl) return -1
        return light(nl[0], nl[1], nl[2], b.a) * 0.55
    }
}

/// AirPod Pro: round head with an ear tip on top, stem going down. side "left" | "right" mirrors it.
function podSampler(b, side) {
    var hw = b.w / 2, hh = b.h / 2, m = side === "right" ? -1 : 1
    var headR = b.w * 0.42, headY = -hh + headR, headX = m * (hw - headR) * 0.6
    var tipR = headR * 0.55, tipX = headX - m * headR * 0.75, tipY = headY - headR * 0.25
    var stemW = b.w * 0.2, stemX = m * b.w * 0.08
    return function (x, y) {
        // ear tip (grey silicone), behind the head
        var tx = (x - tipX) / tipR, ty = (y - tipY) / tipR
        var dh = Math.hypot(x - headX, y - headY) / headR
        if (dh <= 1) {
            var nx = (x - headX) / headR, ny = (y - headY) / headR
            return light(nx, ny, Math.sqrt(Math.max(0, 1 - nx * nx - ny * ny)), b.a)
        }
        if (tx * tx + ty * ty <= 1) return light(tx, ty, Math.sqrt(Math.max(0, 1 - tx * tx - ty * ty)), b.a) * 0.6
        // stem: rounded capsule from the head down to the bottom
        if (y > headY && y < hh) {
            var sx = (x - stemX) / stemW
            if (Math.abs(sx) <= 1 && (y < hh - stemW || Math.hypot(sx * stemW, y - (hh - stemW)) <= stemW)) {
                return light(sx, 0, Math.sqrt(Math.max(0, 1 - sx * sx)), b.a)
            }
        }
        return -1
    }
}

/// one letter/digit of the 5x7 font filling the body, bevelled: pixel edges next to empty pixels catch light
function glyphSampler(b, ch) {
    var rows = glyphRows(ch), pw = b.w / 5, ph = b.h / 7
    var on = function (c, r) { return r >= 0 && r < 7 && c >= 0 && c < 5 && rows[r][c] === "#" }
    return function (x, y) {
        var c = Math.floor((x + b.w / 2) / pw), r = Math.floor((y + b.h / 2) / ph)
        if (!on(c, r)) return -1
        var fx = (x + b.w / 2) / pw - c - 0.5, fy = (y + b.h / 2) / ph - r - 0.5
        var nx = 0, ny = 0
        if (fx < -0.2 && !on(c - 1, r)) nx = -0.6
        if (fx > 0.2 && !on(c + 1, r)) nx = 0.6
        if (fy < -0.2 && !on(c, r - 1)) ny = -0.6
        if (fy > 0.2 && !on(c, r + 1)) ny = 0.6
        return light(nx, ny, Math.sqrt(Math.max(0.1, 1 - nx * nx - ny * ny)), b.a)
    }
}

/// all grid cells covered by the body: [{col, row, ch, shade}]
function rasterize(b, cw, ch, sampler) {
    var R = Math.hypot(b.w, b.h) / 2 + 2
    var c0 = Math.floor((b.x - R) / cw), c1 = Math.floor((b.x + R) / cw)
    var r0 = Math.floor((b.y - R) / ch), r1 = Math.floor((b.y + R) / ch)
    var cs = Math.cos(-b.a), sn = Math.sin(-b.a), out = []
    for (var r = r0; r <= r1; r++) {
        for (var c = c0; c <= c1; c++) {
            var dx = (c + 0.5) * cw - b.x, dy = (r + 0.5) * ch - b.y
            var s = sampler(dx * cs - dy * sn, dx * sn + dy * cs)
            if (s < 0) continue
            out.push({ col: c, row: r, ch: RAMP[Math.min(RAMP.length - 1, Math.floor(s * RAMP.length))], shade: s })
        }
    }
    return out
}
