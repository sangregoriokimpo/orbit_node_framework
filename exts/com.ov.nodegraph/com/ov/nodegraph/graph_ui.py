from __future__ import annotations
import math
import omni.ui as ui
from com.ov.core.service import OrbitService

# ── appearance ────────────────────────────────────────────────────
BODY_R       = 14
ATTRACTOR_R  = 24
TOOLTIP_W    = 240
TOOLTIP_H    = 160
ORBIT_ASPECT = 0.55      # ry = rx * aspect
MIN_RX       = 60        # minimum orbit ring rx in px
MAX_RX_FRAC  = 0.44      # max rx as fraction of half canvas width
PADDING      = 60        # keep orbits away from window edge

COL_BG         = 0xFF0D0D14
COL_TEXT       = 0xFFFFFFFF
COL_ORBIT_LINE = 0x55FFFFFF
COL_TOOLTIP_BG = 0xEE1A1A2A
COL_TOOLTIP_BD = 0xFFAAAAAA

DEPTH_COLORS = [
    0xFFD4A034,
    0xFF4488DD,
    0xFF44BB66,
    0xFFCC7733,
    0xFF9944CC,
    0xFFDD4455,
]

SEG_SIZE = 2
SEG_GAP  = 5


def _depth_color(d: int) -> int:
    return DEPTH_COLORS[d % len(DEPTH_COLORS)]


# ── drawing ───────────────────────────────────────────────────────

def _dot(px: int, py: int, color: int):
    with ui.Placer(offset_x=px, offset_y=py):
        ui.Rectangle(
            width=SEG_SIZE, height=SEG_SIZE,
            style={"background_color": color, "border_width": 0},
        )


def _draw_ellipse(cx, cy, rx, ry, color, n=180):
    if rx < 4 or ry < 2:
        return
    prev_x = cx + rx
    prev_y = cy
    for i in range(1, n + 1):
        a     = 2 * math.pi * i / n
        cur_x = cx + rx * math.cos(a)
        cur_y = cy + ry * math.sin(a)
        dx    = cur_x - prev_x
        dy    = cur_y - prev_y
        seg   = math.sqrt(dx * dx + dy * dy)
        if seg < 0.5:
            prev_x, prev_y = cur_x, cur_y
            continue
        steps  = max(int(seg / SEG_GAP), 1)
        ux, uy = dx / seg, dy / seg
        for j in range(steps):
            t = j / steps * seg
            _dot(int(prev_x + ux * t), int(prev_y + uy * t), color)
        prev_x, prev_y = cur_x, cur_y


# ── tree helpers ──────────────────────────────────────────────────

def _build_tree(svc: OrbitService):
    bodies   = svc.list_bodies()
    body_set = set(bodies)
    children_of: dict[str, list[str]] = {}
    parent_of:   dict[str, str]       = {}
    for p in bodies:
        b = svc.get_body(p)
        if not b:
            continue
        parent_of[p] = b.attractor_path
        children_of.setdefault(b.attractor_path, [])
        children_of.setdefault(p, [])
        children_of[b.attractor_path].append(p)
    all_nodes = set(children_of.keys())
    roots = [n for n in all_nodes if n not in body_set]
    if not roots:
        roots = [n for n in all_nodes if n not in parent_of]
    return children_of, roots, body_set


def _collect_rmags(node: str, children_of: dict, svc: OrbitService) -> list[float]:
    """Collect all |r| values in this subtree."""
    vals = []
    b = svc.get_body(node)
    if b:
        r = b.r
        vals.append(math.sqrt(r[0]**2 + r[1]**2 + r[2]**2))
    for kid in children_of.get(node, []):
        vals.extend(_collect_rmags(kid, children_of, svc))
    return vals


# ── main UI ───────────────────────────────────────────────────────

class NodeGraphUI:
    def __init__(self, svc: OrbitService):
        self._svc         = svc
        self._win         = ui.Window("Orbit Diagram", width=1100, height=750)
        self._orbit_layer: ui.ZStack | None = None
        self._body_layer:  ui.ZStack | None = None
        self._tooltip:     ui.ZStack | None = None
        self._tt_label:    ui.Label  | None = None
        self._build_window()

    def _build_window(self):
        with self._win.frame:
            with ui.VStack(spacing=0):
                with ui.HStack(height=28):
                    ui.Label("Orbit Diagram", width=200)
                    ui.Button("Refresh", width=80, clicked_fn=self.refresh)
                with ui.ZStack():
                    ui.Rectangle(style={"background_color": COL_BG})
                    self._orbit_layer = ui.ZStack()
                    self._body_layer  = ui.ZStack()
                    self._tooltip = ui.ZStack(
                        width=TOOLTIP_W, height=TOOLTIP_H, visible=False,
                    )
                    with self._tooltip:
                        ui.Rectangle(style={
                            "background_color": COL_TOOLTIP_BG,
                            "border_width": 1,
                            "border_color": COL_TOOLTIP_BD,
                            "border_radius": 6,
                        })
                        with ui.VStack(style={"margin": 10}):
                            self._tt_label = ui.Label(
                                "", word_wrap=True,
                                style={"color": COL_TEXT, "font_size": 12},
                            )
        self.refresh()

    def refresh(self):
        cw = max(self._win.width  - 24, 500)
        ch = max(self._win.height - 60, 400)
        children_of, roots, body_set = _build_tree(self._svc)
        self._orbit_layer.clear()
        self._body_layer.clear()
        self._counter    = 1
        self._node_nums: dict[str, int] = {}

        # ── build a global r -> px scale for each root cluster ────
        # collect all rmags across every root to get a consistent scale
        all_rmags = []
        for root in roots:
            all_rmags.extend(_collect_rmags(root, children_of, self._svc))

        r_min = min(all_rmags) if all_rmags else 1.0
        r_max = max(all_rmags) if all_rmags else 1.0
        if r_max == r_min:
            r_max = r_min + 1.0

        # map r -> px: MIN_RX .. max_rx
        n_roots = max(len(roots), 1)
        max_rx  = (cw / n_roots) * MAX_RX_FRAC - PADDING

        def r_to_px(rmag: float) -> float:
            t = (rmag - r_min) / (r_max - r_min)
            return MIN_RX + t * (max_rx - MIN_RX)

        for idx, root in enumerate(roots):
            cx = cw * (idx + 0.5) / n_roots
            cy = ch * 0.5
            self._draw_system(root, children_of, body_set,
                               cx=cx, cy=cy, depth=0,
                               r_to_px=r_to_px,
                               canvas_w=cw, canvas_h=ch)

    # ── recursive draw ────────────────────────────────────────────

    def _draw_system(self, node, children_of, body_set,
                     cx, cy, depth, r_to_px, canvas_w, canvas_h):

        kids = children_of.get(node, [])
        is_attractor = node not in body_set
        r     = ATTRACTOR_R if is_attractor else BODY_R
        color = _depth_color(depth)

        if not is_attractor and node not in self._node_nums:
            self._node_nums[node] = self._counter
            self._counter += 1

        label = "0" if is_attractor else str(self._node_nums.get(node, "?"))
        tt    = self._build_tooltip(node, depth)
        self._place_body(cx, cy, r, color, label, tt, canvas_w, canvas_h)

        if not kids:
            return

        n_kids = len(kids)
        for i, kid in enumerate(kids):
            b = self._svc.get_body(kid)
            if b:
                rmag = math.sqrt(b.r[0]**2 + b.r[1]**2 + b.r[2]**2)
                rx   = r_to_px(rmag)
            else:
                rx = MIN_RX

            ry = rx * ORBIT_ASPECT

            # draw orbit ellipse centred on parent
            with self._orbit_layer:
                _draw_ellipse(cx, cy, rx, ry, COL_ORBIT_LINE)

            # spread kids at equal angles around ellipse
            angle  = (2 * math.pi / n_kids) * i - math.pi / 2
            kid_cx = cx + rx * math.cos(angle)
            kid_cy = cy + ry * math.sin(angle)

            self._draw_system(kid, children_of, body_set,
                               cx=kid_cx, cy=kid_cy,
                               depth=depth + 1,
                               r_to_px=r_to_px,
                               canvas_w=canvas_w, canvas_h=canvas_h)

    # ── body widget ───────────────────────────────────────────────

    def _place_body(self, cx, cy, r, color, label, tooltip_text, canvas_w, canvas_h):
        ox = int(cx - r)
        oy = int(cy - r)
        with self._body_layer:
            with ui.Placer(offset_x=ox, offset_y=oy):
                with ui.ZStack(width=r * 2, height=r * 2):
                    ui.Circle(
                        radius=r,
                        style={
                            "background_color": color,
                            "border_width": 2,
                            "border_color": 0xCCFFFFFF,
                        },
                    )
                    ui.Label(
                        label,
                        alignment=ui.Alignment.CENTER,
                        style={"color": COL_TEXT, "font_size": max(int(r * 0.75), 10)},
                    )
                    hover = ui.Rectangle(
                        width=r * 2, height=r * 2,
                        style={"background_color": 0x00000000, "border_width": 0},
                    )

                    def _on_hover(hovered, _tt=tooltip_text, _cx=cx, _cy=cy,
                                  _r=r, _cw=canvas_w, _ch=canvas_h):
                        if not self._tooltip or not self._tt_label:
                            return
                        if hovered:
                            tx = int(_cx + _r + 10)
                            ty = int(_cy - TOOLTIP_H / 2)
                            if tx + TOOLTIP_W > _cw:
                                tx = int(_cx - _r - TOOLTIP_W - 10)
                            ty = max(4, min(ty, int(_ch - TOOLTIP_H - 4)))
                            try:
                                self._tooltip.offset_x = tx
                                self._tooltip.offset_y = ty
                            except Exception:
                                pass
                            self._tt_label.text   = _tt
                            self._tooltip.visible = True
                        else:
                            self._tooltip.visible = False

                    hover.set_mouse_hovered_fn(_on_hover)

    # ── tooltip ───────────────────────────────────────────────────

    def _build_tooltip(self, path: str, depth: int) -> str:
        body  = self._svc.get_body(path)
        short = path.rsplit("/", 1)[-1]
        if body is None:
            return f"{short}\nType : Attractor (static)\nNot a registered orbit body"
        r, v  = body.r, body.v
        rmag  = math.sqrt(r[0]**2 + r[1]**2 + r[2]**2)
        vmag  = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
        attr  = body.attractor_path.rsplit("/", 1)[-1]
        lines = [
            f"{short}",
            f"Orbits  : {attr}",
            f"Mode    : {body.control_mode}",
            f"|r|     : {rmag:.2f}",
            f"|v|     : {vmag:.3f}",
            f"mu      : {body.mu:.3f}",
            f"dt_sim  : {body.dt_sim:.4f}",
        ]
        if body.control_mode == "pd":
            lines.append(f"Kp={body.kp}  Kd={body.kd}  amax={body.a_max}")
        return "\n".join(lines)

    def destroy(self):
        if self._win:
            self._win.visible = False
            self._win = None