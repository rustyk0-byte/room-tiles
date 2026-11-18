# Desk stands for Elecrow CrowPanel Advanced ESP32-P4 panels

3D-printable desk stands for the 7" and 10.1" panels. Each stand is three parts:

- a thin-bezel **frame** that the board screws into;
- a **back cover** that screws onto the frame;
- a one-piece **stand**.

The screen slides down onto two tapered dovetail rails on the stand. No screws hold it to the stand, and it seats snugly with no play. An arch under the stand's arm keeps the screen from bouncing when you tap it.

## Which file fits which panel

| Files | Panel | Board versions |
|---|---|---|
| `desk-stand-7in-*.stl`, `desk-stand-7in.scad` | Elecrow CrowPanel Advanced 7" ESP32-P4 (1024×600) | V1.0, V1.1 and V1.2 (same outline and mounting holes) |
| `desk-stand-10in-*.stl`, `desk-stand-10in.scad` | Elecrow CrowPanel Advanced 10.1" ESP32-P4 (1024×600) | — |

Each size has a `-frame`, `-cover` and `-stand` STL. The STLs are already in print orientation.

| | 7" | 10.1" |
|---|---|---|
| Frame (W × H × D) | 183.4 × 124.5 × 27.3 mm | 253.5 × 167.5 × 29.1 mm |
| Smallest bed | 190 × 190 mm (the frame is 183.4 mm wide) | 256 × 256 mm (the frame is 253.5 mm wide) |
| Screen angle | leans back 20°, lowest edge 40 mm above the desk | same |

## Print settings

| Part | Orientation | Settings |
|---|---|---|
| Frame | Front face down | PLA, 0.2 mm layers, 3 walls, 15% infill |
| Cover | Back face down | PLA, 0.2 mm layers, 3 walls, 15% infill |
| Stand | Standing on its foot, as it sits on the desk | PLA or HT-PLA, 0.2 mm layers, 4 walls, 20% gyroid infill |

- **No supports needed for any part.** Every overhang is 45° or steeper, and the few bridges are short, about 10 mm.
- **Use PLA or HT-PLA for the stand.** PETG tends to sag on the stand's 45–52° curves.
- A textured PEI plate works well for the frame's front face.

## Hardware

| | Qty | Used for |
|---|---|---|
| M3 × 6 mm self-tapping screws, socket cap | 4 | Board to frame. Don't use longer screws: the pilot holes are blind, and a longer screw can push through the front bezel. |
| M3 × 10 mm self-tapping screws, socket cap | 4 | Cover to frame. The heads sit flush in counterbores. |
| Rubber feet or anti-slip tape | — | Under the stand's foot |

No heat-set inserts are needed, and no screws hold the screen to the stand.

**Power:** the panel runs from a 5 V supply into its **UART3-IN** connector (XH2.54, 4-pin: pin 3 = +5 V, pin 4 = GND). A USB-C PD trigger board set to **5 V** works well. The cable leaves through a slot in the cover and passes through the stand.

## Assembly

1. **Board into the frame.** Lay the frame face down, drop the board in glass first, and fix it with 4 × M3 × 6.
2. **Power cable.** Plug the 5 V lead into UART3-IN. Thread the cable out through the slot in the floor of the channel in the cover.
3. **Cover onto the frame.** Fix it with 4 × M3 × 10.
4. **Cable through the stand.** Push the cable through the long slot in the stand's pad, from the front.
5. **Screen onto the stand.**
   - Hold the screen a little above its final position, about 16 mm for the 7" and 26 mm for the 10.1", with the back of the cover against the stand's pad. The two rails drop into the wide lower part of the cover's channel.
   - Slide the screen down until it stops. The dovetail is tapered, so it starts loose and finishes snug, and the screen's weight keeps it seated.

To remove the screen, lift it straight up. Pick the whole thing up by the stand, not by the screen, or the stand can slide off.

## Customizing

Open the `.scad` file in [OpenSCAD](https://openscad.org). Set `part` to `"frame"`, `"cover"`, `"stand"` or `"assembly"`, then export an STL.

- **USB-C ports:** by default the board's USB-C ports are hidden inside the frame. To plug a cable into them while the screen is in its frame, set `usb_ports_exposed = true`. Then set `usb_ports_side` to `"left"` or `"right"`, as seen from the front, to match the side the ports will be on. Only that side wall gets openings.
- **Slide fit:** if your printer prints the dovetail tight and the screen sits noticeably high, raise `fit` (for example to `0.05`). If it's loose and you can feel play, lower it (for example to `-0.05`).
- **Space behind the board:** about 17 mm on the 7" and about 18 mm on the 10.1", enough for the UART3-IN plug and its wires. Right behind the slide-mount channel, in the upper middle of the cover, it drops to 13.2 mm (7") and 14.2 mm (10.1").

## License

Apache-2.0, the same as the rest of this repository.
