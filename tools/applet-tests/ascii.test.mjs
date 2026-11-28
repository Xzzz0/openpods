import { load, check } from "./load.mjs";
const A = load("../../plasmoid/org.openpods.applet/contents/ui/ascii.js",
               ["RAMP", "glyphRows", "caseSampler", "podSampler", "glyphSampler", "rasterize"]);

check("ramp is the one from ascii-art", A.RAMP === ".:;=+*xo%#&@");
const chars = "OPENPODS0123456789.-ABCXYZ";
check("block font: 7 rows of 5 for every char", [...chars].every(c => {
  const r = A.glyphRows(c); return r.length === 7 && r.every(l => l.length === 5);
}));
check("unknown char falls back to a box", A.glyphRows("§").join("") === A.glyphRows("\u0000").join("") &&
      A.glyphRows("§")[0] === "#####");
check("lowercase maps to uppercase", A.glyphRows("o").join() === A.glyphRows("O").join());

const span = cells => {
  const cs = cells.map(c => c.col), rs = cells.map(c => c.row);
  return { w: Math.max(...cs) - Math.min(...cs) + 1, h: Math.max(...rs) - Math.min(...rs) + 1 };
};
const box = (w, h, a = 0) => ({ x: 200, y: 200, w, h, a });
const cw = 7, chh = 14;

const caseB = box(130, 100);
const closed = A.rasterize(caseB, cw, chh, A.caseSampler(caseB, false));
const open = A.rasterize(caseB, cw, chh, A.caseSampler(caseB, true));
const s = span(closed);
check("case is drawn, wider than tall (in pixels)", closed.length > 50 && s.w * cw > s.h * chh, JSON.stringify(s));
check("open lid looks different", JSON.stringify(open) !== JSON.stringify(closed));
check("only ramp characters", [...closed, ...open].every(c => A.RAMP.includes(c.ch)));
check("shades in 0..1", closed.every(c => c.shade >= 0 && c.shade <= 1));

const pod = box(34, 70);
const pc = A.rasterize(pod, cw, chh, A.podSampler(pod, "left"));
const centreRow = Math.floor(pod.y / chh);
check("pod has a stem below its centre", pc.some(c => c.row > centreRow + 1), `cells=${pc.length}`);

const g = box(5 * cw, 7 * chh);  // one grid cell per font pixel, as in the window
const gc = A.rasterize(g, cw, chh, A.glyphSampler(g, "O"));
const mid = gc.find(c => c.col === Math.floor(g.x / cw) && c.row === Math.floor(g.y / chh));
check("glyph O has a hole in the middle", gc.length > 10 && !mid);

const rot = box(130, 100, Math.PI / 2);
const rs = span(A.rasterize(rot, cw, chh, A.caseSampler(rot, false)));
check("rotated 90° case is taller than wide (in pixels)", rs.h * chh > rs.w * cw, JSON.stringify(rs));
