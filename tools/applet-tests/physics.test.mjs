import { load, check } from "./load.mjs";
const { World } = load("../../plasmoid/org.openpods.applet/contents/ui/physics.js", ["World"]);
const run = (w, secs, ax = 0, ay = 0) => { for (let i = 0; i < secs * 120; i++) w.step(1 / 120, ax, ay); };

{ // gravity: falls and rests on the floor
  const w = new World(400, 500); const b = w.addBody({ x: 200, y: 50, w: 40, h: 20 });
  run(w, 3);
  check("falls and rests on floor", Math.abs(b.y + 10 - 500) < 2 && Math.abs(b.vy) < 1, `y=${b.y.toFixed(1)} vy=${b.vy.toFixed(2)}`);
}
{ // walls contain a very fast body
  const w = new World(400, 500); const b = w.addBody({ x: 200, y: 250, w: 30, h: 30 });
  b.vx = 5000; b.vy = -5000; run(w, 2);
  check("fast body stays inside", b.x > 0 && b.x < 400 && b.y > 0 && b.y < 500, `x=${b.x.toFixed(1)} y=${b.y.toFixed(1)}`);
}
{ // two boxes don't overlap
  const w = new World(400, 500);
  const a = w.addBody({ x: 200, y: 400, w: 60, h: 30 }); const b = w.addBody({ x: 205, y: 300, w: 60, h: 30 });
  run(w, 2);
  const dy = Math.abs(a.y - b.y);
  check("stacked boxes don't overlap", dy > 28, `dy=${dy.toFixed(1)}`);
}
{ // resting pile settles
  const w = new World(400, 500);
  for (let i = 0; i < 8; i++) w.addBody({ x: 120 + (i % 4) * 50, y: 100 + Math.floor(i / 4) * 40, w: 36, h: 24 });
  run(w, 4);
  const e = w.bodies.reduce((s, b) => s + b.vx * b.vx + b.vy * b.vy + b.va * b.va, 0);
  check("pile settles", e < 1e-2, `energy=${e.toExponential(2)}`);
}
{ // window moves right -> contents pushed left
  const w = new World(400, 500); const b = w.addBody({ x: 200, y: 480, w: 30, h: 30 });
  run(w, 1);  // settle
  const x0 = b.x; for (let i = 0; i < 12; i++) w.step(1 / 120, 6000, 0);
  run(w, 0.3);
  check("window acceleration shakes contents", b.x < x0 - 5, `dx=${(b.x - x0).toFixed(1)}`);
}
{ // grab, drag, release throws
  const w = new World(400, 500); const b = w.addBody({ x: 100, y: 250, w: 30, h: 30 });
  check("bodyAt finds body", w.bodyAt(105, 252) === b && w.bodyAt(300, 50) === null);
  w.grab(b, 100, 250);
  for (let i = 1; i <= 10; i++) { w.drag(100 + i * 10, 250); w.step(1 / 120, 0, 0); }
  w.release();
  check("release throws with drag velocity", b.vx > 300, `vx=${b.vx.toFixed(0)}`);
}
