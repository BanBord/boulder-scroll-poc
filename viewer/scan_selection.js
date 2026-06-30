// Pure-function selection logic for the wall-scan viewer.
// No DOM, no Canvas — usable from scan.html and scan_tests.html alike.

const AB_EPS_DEFAULT = 18;
const MAX_NEIGHBOR_FRAC_DEFAULT = 0.18;
// Double-start window: 2nd start tag within 12 % height + 25 % width of 1st.
const DOUBLE_START_DY_FRAC = 0.12;
const DOUBLE_START_DX_FRAC = 0.25;

export function pointInPolygon(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    const intersect = ((yi > y) !== (yj > y)) &&
      (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

export function growRoute({anchorId, holds, abEps = AB_EPS_DEFAULT,
                           maxNeighborFrac = MAX_NEIGHBOR_FRAC_DEFAULT,
                           imageSize}) {
  const byId = new Map(holds.map(h => [h.id, h]));
  const anchor = byId.get(anchorId);
  if (!anchor) return new Set();
  const [W, H] = imageSize;
  const diag = Math.sqrt(W * W + H * H);
  const aTarget = anchor.color_lab[1];
  const bTarget = anchor.color_lab[2];

  const route = new Set([anchorId]);
  let frontier = [anchor];
  while (frontier.length > 0) {
    const next = [];
    for (const F of frontier) {
      for (const nId of (F.neighbors || [])) {
        if (route.has(nId)) continue;
        const N = byId.get(nId);
        if (!N) continue;
        const dA = N.color_lab[1] - aTarget;
        const dB = N.color_lab[2] - bTarget;
        const dAB = Math.sqrt(dA * dA + dB * dB);
        if (dAB > abEps) continue;
        const dx = N.center[0] - F.center[0];
        const dy = N.center[1] - F.center[1];
        const dSpatial = Math.sqrt(dx * dx + dy * dy) / diag;
        if (dSpatial > maxNeighborFrac) continue;
        route.add(nId);
        next.push(N);
      }
    }
    frontier = next;
  }
  return route;
}

export function assignStartTopFromTags({routeIds, tags, holds, imageSize}) {
  const ids = (routeIds instanceof Set) ? routeIds : new Set(routeIds);
  const inRoute = tags.filter(t => ids.has(t.nearest_hold_id));
  if (inRoute.length === 0) return null;

  if (inRoute.length === 1) {
    const t = inRoute[0];
    const ys = [];
    const byId = new Map(holds.map(h => [h.id, h]));
    for (const hid of ids) ys.push(byId.get(hid).center[1]);
    const median = ys.slice().sort((a, b) => a - b)[Math.floor(ys.length / 2)];
    if (t.center[1] >= median) {
      return {startIds: [t.nearest_hold_id], topId: null, source: 'tags'};
    } else {
      return {startIds: [], topId: t.nearest_hold_id, source: 'tags'};
    }
  }

  const sortedByYDesc = inRoute.slice().sort((a, b) => b.center[1] - a.center[1]);
  const bottom = sortedByYDesc[0];
  const second = sortedByYDesc[1];
  const [W, H] = imageSize;
  const dy = (bottom.center[1] - second.center[1]) / H;
  const dx = Math.abs(bottom.center[0] - second.center[0]) / W;
  const startIds = [bottom.nearest_hold_id];
  if (dy <= DOUBLE_START_DY_FRAC && dx <= DOUBLE_START_DX_FRAC) {
    startIds.push(second.nearest_hold_id);
  }
  const sortedByYAsc = inRoute.slice().sort((a, b) => a.center[1] - b.center[1]);
  const topTag = sortedByYAsc.find(t => !startIds.includes(t.nearest_hold_id));
  const topId = topTag ? topTag.nearest_hold_id : null;
  return {startIds, topId, source: 'tags'};
}

export function assignStartTopSpatial({routeIds, holds, imageSize}) {
  const byId = new Map(holds.map(h => [h.id, h]));
  const list = Array.from(routeIds).map(id => byId.get(id)).filter(Boolean);
  if (list.length === 0) return {startIds: [], topId: null, source: 'spatial'};
  if (list.length === 1) {
    return {startIds: [list[0].id], topId: list[0].id, source: 'spatial'};
  }
  const sortedYAsc = list.slice().sort((a, b) => a.center[1] - b.center[1]);
  const topId = sortedYAsc[0].id;
  const sortedYDesc = list.slice().reverse();
  const bottom = sortedYDesc[0];
  const startIds = [bottom.id];
  const [W, H] = imageSize;
  for (const h of sortedYDesc.slice(1)) {
    const dy = (bottom.center[1] - h.center[1]) / H;
    const dx = Math.abs(bottom.center[0] - h.center[0]) / W;
    if (dy <= DOUBLE_START_DY_FRAC && dx <= DOUBLE_START_DX_FRAC) {
      startIds.push(h.id);
      break;
    }
  }
  return {startIds, topId, source: 'spatial'};
}

export function assignStartTop({routeIds, tags, holds, imageSize}) {
  const fromTags = assignStartTopFromTags({routeIds, tags, holds, imageSize});
  if (fromTags && (fromTags.startIds.length > 0 || fromTags.topId !== null)) {
    return fromTags;
  }
  return assignStartTopSpatial({routeIds, holds, imageSize});
}
