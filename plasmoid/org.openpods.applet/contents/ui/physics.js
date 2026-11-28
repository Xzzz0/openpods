.pragma library
/*
 * Tiny 2D rigid-body physics for the About window: rotating boxes, gravity, walls, box-box contacts
 * (SAT + impulses with friction), mouse grab/throw and an accelerating frame (the window being moved).
 * Units: pixels, seconds. y grows downwards.
 */

var GRAVITY = 1400
var MAX_SPEED = 3000
var RESTITUTION = 0.35
var FRICTION = 0.4
var ITERATIONS = 6
var SLEEP_SPEED = 6        // px/s (and rad/s * 20) below which a resting body counts as still
var SLEEP_FRAMES = 40

function World(width, height) {
    this.w = width
    this.h = height
    this.bodies = []
    this.held = null
}

/// opts: {x, y, w, h, mass?, kind?, data?}; returns the body
World.prototype.addBody = function (o) {
    var mass = o.mass || (o.w * o.h) / 600
    var b = {
        x: o.x, y: o.y, a: o.a || 0, vx: 0, vy: 0, va: 0, w: o.w, h: o.h,
        im: 1 / mass, iI: 12 / (mass * (o.w * o.w + o.h * o.h)),
        kind: o.kind || "", data: o.data || null, still: 0, ghost: false,
    }
    this.bodies.push(b)
    return b
}

function corners(b) {
    var c = Math.cos(b.a), s = Math.sin(b.a), hw = b.w / 2, hh = b.h / 2
    return [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]].map(function (p) {
        return [b.x + p[0] * c - p[1] * s, b.y + p[0] * s + p[1] * c]
    })
}

function inside(b, px, py, pad) {
    var c = Math.cos(-b.a), s = Math.sin(-b.a), dx = px - b.x, dy = py - b.y
    var lx = dx * c - dy * s, ly = dx * s + dy * c
    return Math.abs(lx) <= b.w / 2 + (pad || 0) && Math.abs(ly) <= b.h / 2 + (pad || 0)
}

/// topmost body under the point (null if none); `pad` makes small glyphs easier to catch
World.prototype.bodyAt = function (px, py, pad) {
    for (var i = this.bodies.length - 1; i >= 0; i--) {
        var b = this.bodies[i]
        if (!b.ghost && inside(b, px, py, pad || 0)) return b
    }
    return null
}

World.prototype.grab = function (b, px, py) {
    var c = Math.cos(-b.a), s = Math.sin(-b.a), dx = px - b.x, dy = py - b.y
    this.held = { b: b, lx: dx * c - dy * s, ly: dx * s + dy * c, tx: px, ty: py, hist: [] }
    b.still = 0
}

World.prototype.drag = function (px, py) {
    if (this.held) { this.held.tx = px; this.held.ty = py }
}

/// lets go; the body keeps the velocity of the last ~60 ms of dragging
World.prototype.release = function () {
    var h = this.held
    if (!h) return
    this.held = null
    var hist = h.hist
    if (hist.length >= 2) {
        var a = hist[0], z = hist[hist.length - 1], dt = Math.max(1e-3, z.t - a.t)
        h.b.vx = clampSpeed((z.x - a.x) / dt)
        h.b.vy = clampSpeed((z.y - a.y) / dt)
    }
}

function clampSpeed(v) { return Math.max(-MAX_SPEED, Math.min(MAX_SPEED, v)) }

/// frameAx/frameAy: acceleration of the window itself (px/s²); everything inside feels the opposite
World.prototype.step = function (dt, frameAx, frameAy) {
    var shaken = Math.abs(frameAx) + Math.abs(frameAy) > 50
    var h = this.held
    this.time = (this.time || 0) + dt
    for (var i = 0; i < this.bodies.length; i++) {
        var b = this.bodies[i]
        if (b.ghost) continue
        if (h && h.b === b) {
            // the grab point follows the mouse like a stiff spring; torque from the off-centre grab
            var c = Math.cos(b.a), s = Math.sin(b.a)
            var gx = b.x + h.lx * c - h.ly * s, gy = b.y + h.lx * s + h.ly * c
            var ex = h.tx - gx, ey = h.ty - gy
            b.vx = clampSpeed(ex / dt * 0.5)
            b.vy = clampSpeed(ey / dt * 0.5)
            // spin: the pull at the grab point (r × error) plus gravity swinging the body like a pendulum
            var rx = gx - b.x, ry = gy - b.y, r2 = rx * rx + ry * ry + 100
            b.va = b.va * 0.9 + ((rx * ey - ry * ex) / r2 * 0.4 / dt + (-rx * GRAVITY) / r2 * dt) * 0.5
            h.hist.push({ t: this.time, x: h.tx, y: h.ty })
            while (h.hist.length > 2 && this.time - h.hist[0].t > 0.06) h.hist.shift()
            b.still = 0
        } else {
            if (b.still > SLEEP_FRAMES && !shaken) continue
            b.vy += GRAVITY * dt
            b.vx -= frameAx * dt
            b.vy -= frameAy * dt
            if (shaken) b.still = 0
        }
        b.vx = clampSpeed(b.vx); b.vy = clampSpeed(b.vy)
        b.va = Math.max(-40, Math.min(40, b.va)) * 0.998
    }
    for (i = 0; i < this.bodies.length; i++) {
        b = this.bodies[i]
        if (b.ghost || (b.still > SLEEP_FRAMES && !(h && h.b === b) && !shaken)) continue
        b.x += b.vx * dt; b.y += b.vy * dt; b.a += b.va * dt
    }
    for (var it = 0; it < ITERATIONS; it++) {
        for (i = 0; i < this.bodies.length; i++) {
            if (this.bodies[i].ghost) continue
            for (var j = i + 1; j < this.bodies.length; j++) {
                if (!this.bodies[j].ghost) collide(this.bodies[i], this.bodies[j])
            }
            walls(this.bodies[i], this.w, this.h)
        }
    }
    for (i = 0; i < this.bodies.length; i++) {
        b = this.bodies[i]
        // last line of defence against tunnelling: centre always inside the window
        b.x = Math.max(2, Math.min(this.w - 2, b.x)); b.y = Math.max(2, Math.min(this.h - 2, b.y))
        var moving = Math.abs(b.vx) + Math.abs(b.vy) + Math.abs(b.va) * 20 > SLEEP_SPEED
        b.still = moving ? 0 : b.still + 1
        if (b.still > SLEEP_FRAMES) { b.vx = 0; b.vy = 0; b.va = 0 }
    }
}

// impulse at contact point p along normal n (from a to b; b may be null = static wall)
function impulse(a, b, px, py, nx, ny) {
    var rax = px - a.x, ray = py - a.y
    var rbx = b ? px - b.x : 0, rby = b ? py - b.y : 0
    var vax = a.vx - a.va * ray, vay = a.vy + a.va * rax
    var vbx = b ? b.vx - b.va * rby : 0, vby = b ? b.vy + b.va * rbx : 0
    var rvx = vbx - vax, rvy = vby - vay
    var vn = rvx * nx + rvy * ny
    if (vn > 0) return 0
    var ran = rax * ny - ray * nx, rbn = rbx * ny - rby * nx
    var k = a.im + a.iI * ran * ran + (b ? b.im + b.iI * rbn * rbn : 0)
    var e = Math.abs(vn) < 60 ? 0 : RESTITUTION   // no bouncing at rest
    var jn = -(1 + e) * vn / k
    apply(a, b, rax, ray, rbx, rby, nx * jn, ny * jn)
    // friction along the tangent
    vax = a.vx - a.va * ray; vay = a.vy + a.va * rax
    vbx = b ? b.vx - b.va * rby : 0; vby = b ? b.vy + b.va * rbx : 0
    rvx = vbx - vax; rvy = vby - vay
    var tx = -ny, ty = nx, vt = rvx * tx + rvy * ty
    var rat = rax * ty - ray * tx, rbt = rbx * ty - rby * tx
    var kt = a.im + a.iI * rat * rat + (b ? b.im + b.iI * rbt * rbt : 0)
    var jt = Math.max(-FRICTION * jn, Math.min(FRICTION * jn, -vt / kt))
    apply(a, b, rax, ray, rbx, rby, tx * jt, ty * jt)
    return jn
}

function apply(a, b, rax, ray, rbx, rby, jx, jy) {
    a.vx -= jx * a.im; a.vy -= jy * a.im; a.va -= (rax * jy - ray * jx) * a.iI
    if (b) { b.vx += jx * b.im; b.vy += jy * b.im; b.va += (rbx * jy - rby * jx) * b.iI }
}

function walls(b, W, H) {
    var cs = corners(b), hit = []
    for (var k = 0; k < 4; k++) {
        var p = cs[k]
        if (p[0] < 0) hit.push([p, 1, 0, -p[0]])
        if (p[0] > W) hit.push([p, -1, 0, p[0] - W])
        if (p[1] < 0) hit.push([p, 0, 1, -p[1]])
        if (p[1] > H) hit.push([p, 0, -1, p[1] - H])
    }
    for (k = 0; k < hit.length; k++) {
        var c = hit[k]
        // wall is "a" (static) pushing the body: normal points into the room
        b.x += c[1] * c[3] / Math.max(1, hit.length) * 0.8
        b.y += c[2] * c[3] / Math.max(1, hit.length) * 0.8
        var j = impulseStatic(b, c[0][0], c[0][1], c[1], c[2])
        if (j > 30) b.still = 0
    }
}

// body against a static surface with normal n pointing towards the body
function impulseStatic(b, px, py, nx, ny) {
    return impulse(b, null, px, py, -nx, -ny)
}

function axes(b) {
    var c = Math.cos(b.a), s = Math.sin(b.a)
    return [[c, s], [-s, c]]
}

function project(cs, ax) {
    var mn = Infinity, mx = -Infinity
    for (var i = 0; i < 4; i++) {
        var d = cs[i][0] * ax[0] + cs[i][1] * ax[1]
        if (d < mn) mn = d
        if (d > mx) mx = d
    }
    return [mn, mx]
}

function collide(a, b) {
    var dx = b.x - a.x, dy = b.y - a.y
    var ra = (a.w + a.h) * 0.71, rb = (b.w + b.h) * 0.71
    if (dx * dx + dy * dy > (ra + rb) * (ra + rb) * 0.26) return
    var ca = corners(a), cb = corners(b)
    var all = axes(a).concat(axes(b)), best = Infinity, n = null
    for (var i = 0; i < 4; i++) {
        var pa = project(ca, all[i]), pb = project(cb, all[i])
        var o = Math.min(pa[1], pb[1]) - Math.max(pa[0], pb[0])
        if (o <= 0) return
        if (o < best) { best = o; n = all[i] }
    }
    if (n[0] * dx + n[1] * dy < 0) n = [-n[0], -n[1]]     // normal from a to b
    // contact point: corners of one box that lie inside the other
    var pts = []
    for (i = 0; i < 4; i++) {
        if (inside(a, cb[i][0], cb[i][1], 0.5)) pts.push(cb[i])
        if (inside(b, ca[i][0], ca[i][1], 0.5)) pts.push(ca[i])
    }
    if (!pts.length) pts.push([(a.x + b.x) / 2, (a.y + b.y) / 2])
    // positional correction, split by inverse mass (a held body acts heavy)
    var hold = a.im + b.im
    var corr = Math.max(0, best - 0.5) * 0.6 / hold
    a.x -= n[0] * corr * a.im; a.y -= n[1] * corr * a.im
    b.x += n[0] * corr * b.im; b.y += n[1] * corr * b.im
    var total = 0
    for (i = 0; i < pts.length; i++) total += impulse(a, b, pts[i][0], pts[i][1], n[0], n[1])
    if (total > 30) { a.still = 0; b.still = 0 }
}
