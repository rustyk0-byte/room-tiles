// =====================================================================
// Modern display frame — Elecrow CrowPanel Advanced 7" ESP32-P4 (1024x600)
// SPDX-License-Identifier: Apache-2.0
// The 7" version of the 10.1" design (desk-stand-10in.scad). The stand has no
// screws: the screen slides down onto it.
// All three parts print without supports.
//
//   FRAME  thin-bezel front with a 45° chamfered front edge. The board screws
//          in (4x M3 x 6). Print it face-down on the textured plate (front face
//          on the bed, as modeled).
//   COVER  back cover with a 45° chamfered rear edge, 4 screws into bosses on
//          the frame's top and bottom walls (4x M3 x 10), a center cable slot,
//          and a dovetail channel molded into the back. Print it back-face-down.
//   STAND  one curved ribbon: the foot runs under the screen, bends up at the
//          back, and its pad carries two dovetail rails. A ribbon arch under
//          the arm stops the screen bouncing. Print it standing on its foot, as
//          it sits on the desk.
//
// Mounting the screen on the stand (no screws):
//   1. Push the cable's far end through the slot in the stand's neck from the front.
//   2. Hold the screen about 16 mm higher than its final position, with the back
//      of the cover against the stand's pad, so the two rails drop into the wide
//      lower part of the cover's channel.
//   3. Slide the screen down. The rails run up under the channel's undercut; the
//      dovetail is tapered, so it goes in loose and ends up snug, and the screen's
//      weight keeps it seated. To remove it, lift the screen straight up.
//   Lift the whole thing by the stand, not by the screen.
//
// Board data from Elecrow's Eagle files for the 7" P4 board, V1.0, V1.1 and V1.2.
// The outline and holes are identical in all three:
//   PCB 176.9 x 104.0 x 1.6, M3 holes 3.0 mm from each edge (170.9 x 98.0 apart).
// From Elecrow's 3D model (ESP32-P4-7_0-inch-20251229.stp):
//   glass + LCD 164.9 x 100.0, centered on the board, with the glass front
//   6.1 mm in front of the PCB's front face.
// (A 180 x 105 board with holes 3.5 mm in, i.e. 173 x 98, is a common wrong
//  assumption for this panel: 2.1 mm too wide, so the holes don't line up.)
//
// Hardware (socket-cap self-tapping M3):
//   board to frame   4x M3 x 6
//   cover to frame   4x M3 x 10  heads sit flush in counterbores
// Rubber tape under the foot.
// =====================================================================

part = "assembly"; // "assembly", "frame", "cover", "stand"

$fn = 48;

// ---------- Board ----------
pcb_width = 176.9;
pcb_height = 104.0;
pcb_thickness = 1.6;
pcb_hole_edge_offset = 3.0;
glass_width = 164.9;
glass_height = 100.0;
glass_front = 6.1;          // glass front face, in front of the PCB's front face
// Clear space from the back face of the board to the inside of the cover
// (UART3-IN plug and wires, the USB-C power adapter).
rear_clearance = 17;
// USB-C ports (two, on one short edge) overhang the board edge.
usb_overhang = 1.5;
usb_groove_clearance = 0.5;
usb_port_centers = [-10.47, 10.47];
usb_port_width = 8.94;
usb_port_height = 4.4;
usb_port_center_depth = 2.7; // behind the PCB front face
// USB-C access. By default the ports are hidden inside the frame and the board
// is powered through its UART3-IN connector (5 V). Set usb_ports_exposed = true to
// cut openings in the side wall so USB-C cables can be plugged in while the screen
// is in its frame.
usb_ports_exposed = false;
// Which side the openings go on, as seen from the front: "left" or "right".
// Pick the side the board's USB-C ports will be on (the board fits either way round).
usb_ports_side = "left";
assert(usb_ports_side == "left" || usb_ports_side == "right", "usb_ports_side must be \"left\" or \"right\"");
usb_plug_opening = [13, 7.5]; // opening per port: width x height (fits a typical USB-C plug's overmold)

// ---------- Frame ----------
edge_gap = 3.25;            // outer frame edge to board edge, left and right
// Extra height at the top and bottom, outside the board, for the cover's screw bosses.
cover_boss_band = 7;
frame_width = pcb_width + 2 * edge_gap;                         // 183.4
frame_height = pcb_height + 2 * edge_gap + 2 * cover_boss_band; // 124.5
corner_radius = 5;
wall = 2.4;
front_plate = 3.0;          // bezel thickness
front_chamfer = 3.0;        // 45° front edge; leaves a thin flat bezel
pcb_mount_depth = glass_front + 0.1;  // frame front to PCB front face (glass 0.1 mm recessed)
window_width = glass_width + 1.1;
window_height = glass_height + 1.0;
window_radius = 2;
standoff_diameter = 8;
pilot_diameter = 2.9;       // M3 self-tapping
pilot_front_skin = 1.2;     // solid skin left in front of each blind pilot

// ---------- Back cover ----------
cover_back = 2.5;           // back panel thickness
rear_chamfer = 3.0;         // 45° rear edge
cover_band = 2.0;           // straight band of the cover before the chamfer
cover_screw_pilot = 2.6;
cover_screw_clear = 3.4;
cover_screw_head = 6.2;     // counterbore for a 5.5 mm socket-cap head
cover_screw_head_depth = 3.3;
cover_screw_ring = 3.0;     // extra cover thickness around each cover screw
cover_screw_len = 10;
cover_boss_d = 6.5;
cover_lip = 1.2;
// Cable slot through the back cover (sized so a USB-C plug can be threaded through).
cable_slot = [8, 14];       // width x height (upright; turn a USB-C plug on its side to thread it)
stand_slot_w = 14;          // slot through the stand's pad (lets a plug through)

// UART3-IN (XH2.54 4P) on the back of the board with its plug fitted, used only to
// check the cover clears it (frame coordinates with the USB-C ports at -x, which
// is on the right seen from the front; the 180°-rotated position is checked too).
uart3_box = [[-86.45, -80.75], [-38.44, -25.94]];
uart3_plug_top = glass_front + 0.1 + 1.6 + 15;  // plug + wires 15 mm off the board

// ---------- Stand ----------
tilt = 20;                  // screen leans back from vertical
lowest_point_height = 40;   // desk to the lowest point of the frame/cover
ribbon = 5;                 // ribbon thickness
stand_width = 120;          // foot width
arm_width = 90;             // arm and pad width
foot_rail = 18;             // width of the solid rails around the foot window
foot_corner_radius = 20;    // plan-view radius of the foot's two front corners
foot_front = 10;            // how far the foot reaches in front of the frame's bottom edge
foot_rear = -142;           // rear bend position (as far back as the 45° arm limit allows, for stability)
floor_bend_radius = 12;
pad_bend_radius = 14;

// ---------- Slide-on mount ----------
// Two dovetail rails on the stand's pad slide up into a channel in the back
// of the cover (positions are in cover coordinates, y up from the cover center).
// The dovetail is tapered: the clearance on each flank grows by `taper` per mm
// the screen sits above its seated position, so it slides on loose and seats
// snug with no play. As drawn, the flanks meet about 2.5 mm before the rails
// reach the end of the channel (`stop_ext` of travel is left past the rails),
// so the taper, not the end of the channel, decides where it seats, with room
// either way for print tolerance.
rail_y0 = 33;               // bottom of the rails when mounted
rail_len = 14;
rail_gap = 16;              // clear gap between the rails (the cable runs here)
rail_root = 6;              // width of each rail at the pad (only the outer, angled flank does the work)
rail_h = 3.5;               // how far the rails stand off the pad
dovetail = 60;              // flank angle to the pad face
fit = 0;                    // extra flank clearance: + if it seats too high (tight print), - if it reaches the end of the channel (loose)
taper = 0.02;               // extra clearance per flank per mm above the seated position
stop_ext = 6;               // the channel runs this far past the rails
channel_depth = rail_h + 0.7;  // 0.7 mm over the rail tips, so a slightly sagging channel floor can't rub
slide = rail_len + 2;       // drop-in height above the final position

// Brace: one ribbon arch under the arm, so the screen doesn't bounce when you
// tap it. It stands straight up across the foot's opening; seen from behind
// it's a 1 - cos curve that starts flat at the inner edges of the opening, at
// foot level, and sweeps up into the arm just below the neck.
brace = true;
brace_depth = 12;           // ribbon width (front to back)
brace_half_span = stand_width / 2 - foot_rail + 4;   // flat ends run into the opening's inner edges

// ---------- Derived ----------
board_back_z = pcb_mount_depth + pcb_thickness;
total_depth = board_back_z + rear_clearance + cover_back;
frame_clearance = lowest_point_height + (total_depth - rear_chamfer) * sin(tilt);
split_z = total_depth - rear_chamfer - cover_band;   // frame / cover joint
hole_x = pcb_width / 2 - pcb_hole_edge_offset;
hole_y = pcb_height / 2 - pcb_hole_edge_offset;
cover_screw_inset = rear_chamfer + 3.5;   // 6.5 mm in from the outer edge
// x = ±22.5 keeps the bosses clear of the edge connectors and the display's
// folded flex cables on both long edges, whichever way up the board goes in.
cover_screws = [for (x = [-22.5, 22.5], sy = [-1, 1]) [x, sy * (frame_height / 2 - cover_screw_inset)]];
cover_under_head = total_depth - cover_screw_head_depth - split_z;

// Slide-on mount, derived.
rail_y1 = rail_y0 + rail_len;
rail_in = rail_gap / 2;                       // inner edge of each rail
rail_out = rail_in + rail_root;               // outer edge at the pad
rail_tip = rail_out + rail_h / tan(dovetail); // outer edge at the tip, at the rails' top
rail_widen = taper * rail_len;                // how much wider each rail is at its bottom end
chan_y1 = rail_y1 + stop_ext;                 // top end of the channel
function ch_open(y) = rail_out + fit + taper * (rail_y1 - y);   // channel half-width at the back face
function ch_deep(y) = ch_open(y) + channel_depth / tan(dovetail);
entry_half = rail_tip + rail_widen + 0.5;     // straight-walled entry pocket
entry_y0 = rail_y0 - slide - 0.5;
entry_y1 = rail_y0 - 1;
pad_top_y = rail_y1 + 3;
cable_y = (entry_y0 + entry_y1) / 2;          // cover cable slot center
// The cable hangs at the bottom of the cover's slot; the stand's slot covers it
// over the whole slide.
stand_slot_y0 = entry_y0 + 0.5;
stand_slot_y1 = stand_slot_y0 + slide + 9;
stand_slot = [stand_slot_w, stand_slot_y1 - stand_slot_y0];
stand_slot_y = (stand_slot_y0 + stand_slot_y1) / 2;
block_half = entry_half + 4;
block_y0 = entry_y0 - 3;
block_y1 = chan_y1 + 3;
block_t = channel_depth + 2.1;                // local back thickness around the channel
pad_flat_y0 = entry_y0 - 4;                   // the pad must sit flat from here up

echo(str("Frame ", frame_width, " x ", frame_height, " x ", total_depth, " mm (frame part ", split_z,
         " + cover ", total_depth - split_z, ")"));
echo(str("Screws: board M3x6 -> ", 6 - pcb_thickness, " mm into a ", pcb_mount_depth - pilot_front_skin,
         " mm pilot; cover M3x", cover_screw_len, " -> ", cover_screw_len - cover_under_head, " mm into the boss"));

// ---------- Helpers ----------
// A slab from y0 to y1 whose half-width runs from w0 (at y0) to w1 (at y1).
module taper_slab(y0, y1, w0, w1, z, h) {
    translate([0, 0, z]) linear_extrude(height = h)
        polygon([[-w0, y0], [w0, y0], [w1, y1], [-w1, y1]]);
}
module rr(w, h, r) {
    rr_ = max(min(r, w / 2 - 0.01, h / 2 - 0.01), 0.01);
    offset(r = rr_) square([w - 2 * rr_, h - 2 * rr_], center = true);
}

// Frame local coordinates: x across, y up, z rearward from the front face.
oy = -frame_height / 2 * sin(tilt);
oz = frame_clearance + frame_height / 2 * cos(tilt);
function world(p) = [p[0],
                     -p[2] * cos(tilt) - p[1] * sin(tilt) + oy,
                     -p[2] * sin(tilt) + p[1] * cos(tilt) + oz];
module to_world() {
    translate([0, oy, oz]) rotate([tilt, 0, 0]) rotate([90, 0, 0]) children();
}

// ---------- FRAME ----------
module frame_outer() {
    hull() {
        linear_extrude(height = 0.01)
            rr(frame_width - 2 * front_chamfer, frame_height - 2 * front_chamfer,
               corner_radius - front_chamfer);
        translate([0, 0, front_chamfer])
            linear_extrude(height = split_z - front_chamfer)
                rr(frame_width, frame_height, corner_radius);
    }
}

module frame_part() {
    difference() {
        union() {
            difference() {
                frame_outer();
                translate([0, 0, front_plate])
                    linear_extrude(height = split_z)
                        rr(frame_width - 2 * wall, frame_height - 2 * wall, corner_radius - wall);
            }
            // PCB standoffs, trimmed to the frame's outer shape (otherwise they poke
            // 0.75 mm out through the front chamfer near each corner).
            intersection() {
                frame_outer();
                for (x = [-hole_x, hole_x], y = [-hole_y, hole_y])
                    translate([x, y, 0]) cylinder(d = standoff_diameter, h = pcb_mount_depth);
            }
            // Cover-screw bosses beside the board's top and bottom edges, tied to
            // the wall and standing on the bezel plate (no overhangs).
            for (p = cover_screws)
                hull() {
                    translate([p[0], p[1], front_plate - 0.01]) cylinder(d = cover_boss_d, h = split_z - front_plate + 0.01);
                    translate([p[0] - cover_boss_d / 2, sign(p[1]) * (frame_height / 2 - wall + 0.3) - 0.5, front_plate - 0.01])
                        cube([cover_boss_d, 1, split_z - front_plate + 0.01]);
                }
        }
        // Screen window, carried back to the PCB plane so the standoffs clear the glass.
        translate([0, 0, -1])
            linear_extrude(height = pcb_mount_depth + 1)
                rr(window_width, window_height, window_radius);
        // Cover-screw pilots.
        for (p = cover_screws)
            translate([p[0], p[1], split_z - (cover_screw_len - cover_under_head) - 1]) cylinder(d = cover_screw_pilot, h = 20);
        // Blind M3 pilots from the back.
        for (x = [-hole_x, hole_x], y = [-hole_y, hole_y])
            translate([x, y, pilot_front_skin]) cylinder(d = pilot_diameter, h = pcb_mount_depth);
        // Optional openings for USB-C plugs (usb_ports_exposed).
        if (usb_ports_exposed)
            for (s = usb_ports_side == "left" ? [1] : [-1], yc = usb_port_centers)
                translate([s * (frame_width / 2 - wall / 2), yc, pcb_mount_depth + usb_port_center_depth])
                    cube([3 * wall, usb_plug_opening[0], usb_plug_opening[1]], center = true);
        // USB-C grooves inside both side walls (the board can go in either way round).
        for (side = [0, 1], yc = usb_port_centers)
            mirror([side, 0, 0]) {
                gx = -pcb_width / 2 - usb_overhang - usb_groove_clearance;
                z0 = pcb_mount_depth + usb_port_center_depth - usb_port_height / 2 - usb_groove_clearance;
                translate([gx, yc - usb_port_width / 2 - usb_groove_clearance, z0])
                    cube([-frame_width / 2 + wall - gx + 0.5,
                          usb_port_width + 2 * usb_groove_clearance, split_z]);
            }
    }
}

// ---------- COVER ----------
module cover_outer() {
    hull() {
        translate([0, 0, split_z])
            linear_extrude(height = cover_band)
                rr(frame_width, frame_height, corner_radius);
        translate([0, 0, total_depth - 0.01])
            linear_extrude(height = 0.01)
                rr(frame_width - 2 * rear_chamfer, frame_height - 2 * rear_chamfer,
                   corner_radius - rear_chamfer);
    }
}

module cover_inner() {
    c = rear_chamfer;
    hull() {
        translate([0, 0, split_z - 1])
            linear_extrude(height = total_depth - cover_back - (c - wall) - split_z + 1)
                rr(frame_width - 2 * wall, frame_height - 2 * wall, corner_radius - wall);
        translate([0, 0, total_depth - cover_back - 0.01])
            linear_extrude(height = 0.01)
                rr(frame_width - 2 * c, frame_height - 2 * c, corner_radius - c);
    }
}

// The dovetail channel in the back of the cover: a straight-walled entry
// pocket at the bottom (the rails drop in here), then the undercut section
// the rails slide up into. Between the rails the cover is solid all the way to
// the back face, so the only part of the floor that prints as a ceiling is the
// strip over each rail, about 9 mm across.
module channel_cut() {
    zb = total_depth;
    difference() {
        union() {
            // Entry pocket.
            translate([-entry_half, entry_y0, zb - channel_depth]) cube([2 * entry_half, entry_y1 - entry_y0 + 0.01, channel_depth + 1]);
            // Undercut section: narrow at the back face, wide at the floor, tapering toward the top.
            hull() {
                taper_slab(entry_y1, chan_y1, ch_open(entry_y1), ch_open(chan_y1), zb, 1);
                taper_slab(entry_y1, chan_y1, ch_deep(entry_y1), ch_deep(chan_y1), zb - channel_depth, 0.01);
            }
        }
        // Solid between the rails (0.5 mm clear of their inner edges), the full
        // length of the channel. The cable slot is cut through it separately.
        translate([-(rail_in - 0.5), entry_y0 - 1, zb - channel_depth - 1])
            cube([2 * (rail_in - 0.5), chan_y1 - entry_y0 + 2, channel_depth + 3]);
    }
}

module cover_part() {
    inner_back = total_depth - cover_back;
    difference() {
        union() {
            difference() { cover_outer(); cover_inner(); }
            // Columns from the back panel down to the frame's cover-screw bosses.
            for (p = cover_screws)
                translate([p[0], p[1], split_z]) cylinder(d = cover_boss_d + 1.5, h = inner_back - split_z + 0.01);
            // Locating lips that drop inside the top and bottom walls.
            for (sy = [-1, 1], seg = [[-80, -29], [-16, 16], [29, 80]]) {
                lip_y = sy * (frame_height / 2 - wall - 0.25) - (sy > 0 ? cover_lip : 0);
                translate([seg[0], lip_y, split_z - 3])
                    cube([seg[1] - seg[0], cover_lip, 3.01]);   // stands on the tie below
                // Ties the lip to the cover wall, with a 45° underside so it prints
                // without support back-face-down.
                hull() {
                    translate([seg[0], sy > 0 ? lip_y : lip_y - 1.5, split_z]) cube([seg[1] - seg[0], cover_lip + 1.5, 0.01]);
                    translate([seg[0], sy > 0 ? lip_y + cover_lip + 0.25 : lip_y - 1.5, split_z + 1.5]) cube([seg[1] - seg[0], 1.25, 0.01]);
                }
            }
            // Thicker back around the channel.
            translate([-block_half, block_y0, total_depth - block_t])
                cube([2 * block_half, block_y1 - block_y0, block_t - cover_back + 0.01]);
        }
        // Cover screws: clearance + counterbore so the socket head sits flush.
        for (p = cover_screws) {
            translate([p[0], p[1], split_z - 1]) cylinder(d = cover_screw_clear, h = total_depth);
            translate([p[0], p[1], total_depth - cover_screw_head_depth]) cylinder(d = cover_screw_head, h = 5);
            // 45° cone under the counterbore (prints without support back-face-down).
            translate([p[0], p[1], total_depth - cover_screw_head_depth - (cover_screw_head - cover_screw_clear) / 2])
                cylinder(d1 = cover_screw_clear, d2 = cover_screw_head, h = (cover_screw_head - cover_screw_clear) / 2 + 0.01);
        }
        channel_cut();
        // Cable slot in the floor of the entry pocket.
        translate([0, cable_y, total_depth - block_t - 1])
            linear_extrude(height = block_t + 2) rr(cable_slot[0], cable_slot[1], cable_slot[1] / 2);
    }
}

// ---------- STAND ----------
function v2(p) = [p[1], p[2]];
function nrm(v) = v / norm(v);
function ang(v) = atan2(v[1], v[0]);
function fillet(A, P, C, R, n = 16) =
    let(u1 = nrm(A - P), u2 = nrm(C - P),
        th = acos(u1 * u2) / 2,
        d = R / tan(th),
        ctr = P + nrm(u1 + u2) * (R / sin(th)),
        t1 = P + u1 * d, t2 = P + u2 * d,
        a1 = ang(t1 - ctr), a2 = ang(t2 - ctr),
        da = ((a2 - a1 + 540) % 360) - 180)
    [for (i = [0 : n]) ctr + R * [cos(a1 + da * i / n), sin(a1 + da * i / n)]];
function fillet_d(A, P, C, R) = let(u1 = nrm(A - P), u2 = nrm(C - P)) R / tan(acos(u1 * u2) / 2);

// The pad's bend into the arm ends exactly where the pad has to start sitting flat.
pB = [foot_rear, ribbon / 2];
pF = [foot_front, ribbon / 2];
function pad_pt(y) = v2(world([0, y, total_depth + ribbon / 2]));
pT = pad_pt(pad_top_y);
// Solve for the bend corner so the bend's tangent point lands on pad_flat_y0.
function bend_d(y) = fillet_d(pB, pad_pt(y), pT, pad_bend_radius);
function solve_start(y, k = 0) = k > 30 ? y : solve_start(pad_flat_y0 - bend_d(y), k + 1);
pad_start = solve_start(pad_flat_y0 - 8);
pJ = pad_pt(pad_start);
echo(str("Pad bend corner at cover y = ", pad_start, "; pad flat from ", pad_flat_y0, " to ", pad_top_y));
echo(str("Stand arm angle ", atan2(pJ[1] - pB[1], pJ[0] - pB[0]), " deg from the desk (45+ prints without supports)"));
ribbon_path = concat([pF], fillet(pF, pB, pJ, floor_bend_radius),
                     fillet(pB, pJ, pT, pad_bend_radius), [pT]);

// Width along the path: full foot width up to the floor bend, easing smoothly
// (no creases) through the bend to the arm width.
n_floor = 17;   // index of the last point of the floor bend
// The brace's front face sits 7 mm behind the end of the arm's straight part.
brace_y = ribbon_path[n_floor + 1][0] + nrm(ribbon_path[n_floor + 1] - ribbon_path[n_floor])[1] * ribbon / 2
          - 7 - brace_depth / 2;
function ribbon_w_t(t) = arm_width + (stand_width - arm_width) * (1 + cos(180 * min(1, max(0, t)))) / 2;
function ribbon_w(i) = ribbon_w_t((i - 1) / (n_floor - 1));

module ribbon_3d() {
    for (i = [0 : len(ribbon_path) - 2])
        hull()
            for (j = [i, i + 1])
                translate([0, ribbon_path[j][0], ribbon_path[j][1]])
                    rotate([0, 90, 0])
                        cylinder(d = ribbon, h = ribbon_w(j), center = true, $fn = 32);
}

// The crown just touches the arm's underside at the ribbon's front edge; behind
// that the arm comes lower, so the ribbon is trimmed flush with the underside
// and never goes into the arm. Printing it standing up: just inside the opening
// the underside of the curve is flatter than 45°, so each foot gets a small 45°
// flare down to the bed. The small flat patch under the crown is held by the legs
// on both sides and by the arm behind it, so it prints as a short bridge.
brace_v0 = ribbon / 2;                      // center line of the flat feet: level with the foot
function brace_arm_z(y) = let(a = ribbon_path[n_floor], b = ribbon_path[n_floor + 1],
                              u = nrm(b - a), q = a + [u[1], -u[0]] * (ribbon / 2))
    q[1] + (y - q[0]) * u[1] / u[0];        // height of the arm's underside at y
function brace_x45(A, k = 1) = brace_half_span / 180 * asin(min(1, k * 2 * brace_half_span / (A * PI)));  // where the slope is k (45° for k = 1), from the end
function brace_drop(A) = A * (1 - cos(180 * brace_x45(A) / brace_half_span)) / 2;
brace_overlap = 0.4;        // the ribbon runs this far into the arm, so they fuse
// Rise of the center line: the crown's top meets the arm's underside at the front edge.
function brace_rise() = brace_arm_z(brace_y + brace_depth / 2) + brace_overlap - ribbon / 2 - brace_v0;
function brace_v(x, A) = brace_v0 + A * (1 + cos(180 * x / brace_half_span)) / 2;
module brace_arch_2d() {
    A = brace_rise();
    n = 80;
    pts = [for (i = [0 : n]) let(x = -brace_half_span + 2 * brace_half_span * i / n) [x, brace_v(x, A)]];
    for (i = [0 : len(pts) - 2]) hull() {
        translate(pts[i]) circle(d = ribbon, $fn = 48);
        translate(pts[i + 1]) circle(d = ribbon, $fn = 48);
    }
    // 45° flares under the feet, tangent to the curve where it reaches 45°.
    // The underside's 45° point: offset from the center line's 45° point along its normal.
    xc = brace_half_span - brace_x45(A);
    x45 = xc - ribbon / 2 / sqrt(2);
    v45 = brace_v(xc, A) - ribbon / 2 / sqrt(2);
    for (sx = [-1, 1]) scale([sx, 1])
        polygon(concat([[x45, v45], [x45 + v45, 0], [brace_half_span + ribbon / 2, 0], [brace_half_span + ribbon / 2, brace_v0]],
                       [for (i = [0 : 12]) let(x = brace_half_span - (brace_half_span - xc) * i / 12) [x, brace_v(x, A)]]));
}
module stand_brace() {
    a = ribbon_path[n_floor];
    b = ribbon_path[n_floor + 1];
    u = nrm(b - a);
    at = a + [u[1], -u[0]] * (ribbon / 2 - brace_overlap);   // just inside the arm's underside
    intersection() {
        translate([0, brace_y, 0]) rotate([90, 0, 0])
            linear_extrude(height = brace_depth, center = true) brace_arch_2d();
        translate([0, at[0], at[1]]) rotate([atan2(u[1], u[0]), 0, 0])  // trimmed at the arm's underside
            translate([-200, -300, -300]) cube([400, 600, 300]);
    }
}
echo(str("Brace: stands at y = ", brace_y, ", rises ", brace_rise(), " mm; meets the arm at z = ",
         brace_arm_z(brace_y - brace_depth / 2), " to ", brace_arm_z(brace_y + brace_depth / 2)));

heel_angle = 52;
function heel_reach(r) = r * sin(heel_angle) - r * (1 - cos(heel_angle)) / tan(heel_angle);

module stand_heels() {
    ro = floor_bend_radius + ribbon / 2;          // outer radius of the rear bend
    turn = 180 - atan2(pJ[1] - pB[1], pJ[0] - pB[0]);
    k45 = 1 + ceil(heel_angle / (turn / (n_floor - 1)));  // bend point just past the heel angle
    p1 = ribbon_path[1];
    // Rear: fills only the outside of the bend, below a line at heel_angle that's
    // tangent to the bend, so the inside of the bend stays one smooth curve.
    c = [p1[0], p1[1] + floor_bend_radius];       // center of the bend
    O = function(th, r) c + r * [-sin(th), -cos(th)];
    th_list = [for (i = [0 : 26]) heel_angle * i / 26];
    tp = O(heel_angle, ro);                       // tangent point
    y_bed = tp[0] + tp[1] / tan(heel_angle);      // where the heel line meets the bed
    // bed, up the heel line, then back down just inside the bend (overlapping it)
    profile = concat([[p1[0], 0], [y_bed, 0], tp],
                     [for (i = [26 : -1 : 0]) O(th_list[i], ro - 1)]);
    plan = concat([[stand_width / 2, p1[0] + 1]],
                  [for (th = th_list) [ribbon_w_t(th / turn) / 2, O(th, ro)[0]]],
                  [for (i = [26 : -1 : 0]) [-ribbon_w_t(th_list[i] / turn) / 2, O(th_list[i], ro)[0]]],
                  [[-stand_width / 2, p1[0] + 1]]);
    intersection() {
        rotate([90, 0, 90]) linear_extrude(height = stand_width + 2, center = true) polygon(profile);
        translate([0, 0, -1]) linear_extrude(height = 2 * ro + 2) polygon(plan);
    }
    hull() {
        translate([0, pF[0], pF[1]]) rotate([0, 90, 0]) cylinder(d = ribbon, h = stand_width, center = true, $fn = 32);
        translate([-stand_width / 2, pF[0] + heel_reach(ribbon / 2) - 0.01, 0]) cube([stand_width, 0.01, 0.01]);
    }
}

// Rails in cover coordinates (the pad's front face is at z = total_depth).
// Each one is a little wider at its bottom end (the taper).
module rails_local() {
    zb = total_depth;
    e = rail_h / tan(dovetail);   // bottom end slopes at the dovetail angle (prints without support)
    for (s = [-1, 1]) mirror([s < 0 ? 1 : 0, 0, 0])
        hull() {
            translate([0, 0, zb - 0.01]) linear_extrude(height = 0.6)
                polygon([[rail_in, rail_y0], [rail_out + rail_widen, rail_y0], [rail_out, rail_y1], [rail_in, rail_y1]]);
            translate([0, 0, zb - rail_h]) linear_extrude(height = 0.01)
                polygon([[rail_in, rail_y0 + e], [rail_tip + taper * (rail_y1 - rail_y0 - e), rail_y0 + e],
                         [rail_tip + taper * 0.6, rail_y1 - 0.6], [rail_in, rail_y1 - 0.6]]);
        }
}

module stand_world() {
    // Round the foot's two front corners in plan view.
    intersection() {
        stand_world_raw();
        r = foot_corner_radius;
        translate([0, 0, -1]) linear_extrude(height = 400)
            hull() {
                for (sx = [-1, 1]) translate([sx * (stand_width / 2 - r), foot_front + ribbon - r]) circle(r = r, $fn = 64);
                translate([-stand_width / 2, -400]) square([stand_width, 1]);
            }
    }
}

module stand_world_raw() {
    union() {
        stand_body();
        if (brace) stand_brace();
    }
}

module stand_body() {
    difference() {
        union() {
            ribbon_3d();
            stand_heels();
            to_world() rails_local();
        }
        // Open window in the foot, leaving rails all round.
        translate([0, (foot_front - foot_rail + ribbon_path[1][0] + foot_rail) / 2, -1])
            linear_extrude(height = ribbon + 2)
                rr(stand_width - 2 * foot_rail,
                   (foot_front - foot_rail) - (ribbon_path[1][0] + foot_rail), 10);
        to_world() {
            // Cable slot through the pad, long enough for the slide.
            // (pointed top end so it prints without support)
            translate([0, stand_slot_y, total_depth - 1])
                linear_extrude(height = ribbon + 8) hull() {
                    rr(stand_slot[0], stand_slot[1], stand_slot[0] / 2);
                    translate([0, stand_slot[1] / 2 - stand_slot[0] / 2 + stand_slot[0] / 2 * sqrt(2)]) square(0.01, center = true);
                }
        }
    }
}

// ---------- Screen (for the render only) ----------
module screen_ghost() {
    color("#0c0d10") translate([0, 0, 0.1]) linear_extrude(height = 1.5) rr(glass_width, glass_height, 1);
    color("#1b2a3d") translate([0, 0, 0.05]) linear_extrude(height = 0.1) rr(154.2, 85.9, 0.5);
}

// ---------- Output ----------
// slide_offset > 0 shows the screen lifted by that much (e.g. `slide` = drop-in position).
slide_offset = 0;
if (part == "frame") frame_part();
else if (part == "cover") translate([0, 0, total_depth]) rotate([180, 0, 0]) cover_part();
else if (part == "stand") stand_world();
else if (part == "assembly") {
    to_world() translate([0, slide_offset, 0]) {
        color(frame_color) frame_part();
        color(frame_color) cover_part();
        screen_ghost();
    }
    color(stand_color) stand_world();
}

frame_color = "#2b2e33";
stand_color = "#e8e8e4";
