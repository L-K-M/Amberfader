# Face editor

The face editor runs as a standalone PySide6 application on macOS and Linux.
It previews and edits the same portable face folders that the player loads.
You can design a face without YouTube Music or a playing track.
The standalone editor does not provide a macOS playback bridge.

The editor and rotation support are available in builds from this source tree;
the v0.1.9 release predates them. Use an updated player build to load a face
that declares `controlRotations`.

![Native macOS face editor with a rotated menu button](face-editor-preview.png)

From a source checkout:

```sh
uv sync --extra gui
uv run amberfader-face-editor
uv run amberfader-face-editor /path/to/custom-face
uv run amberfader-face-editor /path/to/custom-face/face.json
```

On Linux, the installed command is `amberfader-face-editor`. With the Flatpak:

```sh
flatpak run --command=amberfader-face-editor ch.lkmc.amberfader
```

Flatpak file access follows its sandbox permissions. Choose an accessible folder
or grant access to the destination when starting the editor.

## Create and edit

Choose a bundled face as your starting template. The editor creates a custom
copy with its own ID and name; it never saves over the bundled artwork. You can
also use **Face editor…** in the player's menu or **Edit a copy…** in the face
picker to start with that face.

Select a control on the canvas or in the control list. Drag it to move it, resize
it with its handles, or adjust its exact position and size in the inspector.
Use the round rotation handle to turn it; hold Shift to snap to 15-degree angles.
Arrow keys move the selected control by one pixel, or ten pixels with Shift.
The inspector also edits its angle, shape, and screen typography. The canvas
shows your current background, sprites, cover aperture, labels, and sliders.
Use zoom and **Snap to 8 px** for placement; hold Option on macOS or Alt on Linux
to bypass the grid during a gesture. Undo or redo to compare edits. A move,
resize, or rotation gesture is one undo step.

The face's drag region is editable too. Keep it clear of playback controls so
the player can distinguish a window drag from a control press. Screen labels,
buttons, artwork, and sliders must fit inside the canvas. Version 1/2 layouts
also require controls to avoid each other and the drag region.
The editor shows validation problems while you arrange controls and blocks
invalid saves. A draft preview can show overlapping controls while you work.
Bounded draft coordinates also allow temporary placement outside the face;
saving still requires every control to fit inside the canvas.

Use the properties panels to adjust the name, ID, author, description, palette,
font, slider style, and cover glass. Per-screen font, size, alignment, and bold
overrides use the same rendering as the player and picker. You can also specify
a font family, italic text, and a text color. Font families depend on what is
installed on your computer. Reset an override to use the face defaults.

## Import Audion faces

Choose **File → Import Audion face…**, then **Browse folder…** or **Browse ZIP…**.
You can select a single converted Audion face folder, a collection of folders,
or a supported ZIP archive. Select a face in the list to preview its conversion;
the filter finds faces by name. The dialog shows the original credits and any
features that could not be converted. Review these notes before choosing
**Import editable copy**.

The import creates an unsaved Amberfader document. It reads the source without
changing or extracting files into it, and keeps the converted images inside
the document. Importing does not install the face or change the player. Use
**Save As** to create a portable face folder, then install it through the player.
Original source credits remain visible in the Face panel and are included in
the saved manifest.

The importer supports Panic's preserved JSON/PNG format containing `index.json`
and its images. Original classic resource-fork and PICT files require conversion
to that format first.

Source ZIPs are limited to 512 MiB, 150,000 entries and 32 MiB of directory
metadata. A collection can contain up to 2048 faces; folder discovery scans up
to 8192 immediate entries. ZIP members must use stored or deflate compression.
Archives are read in place and are never extracted.

Imported version 3 faces can omit elements that the original design did not
contain. Use **Add element…** to add a playback button, screen label, artwork
aperture, or slider. Use **Remove element** to remove the selected control;
the window drag region remains required. Adding and removing elements can be
undone. Version 3 preserves small canvas dimensions and overlapping controls
used by these designs. Existing version 1 and 2 faces retain their layout rules;
removing a control upgrades that document to version 3.

Button artwork may already contain its labels. The Face panel's **Draw labels
over button artwork** option lets you keep the original artwork without drawing
another label over it. Imported sliders may use a popup control when their
original shape cannot be represented by a straight track.

On Flatpak, choose the containing folder so the native file picker can grant
access to the index and its images together. Selecting a ZIP grants access to
one self-contained source. If an image cannot be read, select the folder again
or choose an accessible archive. Unsupported or malformed sources leave your
current face intact.

## Backgrounds and sprites

Import a PNG background or a button-state sprite through the inspector, or drop
a PNG on the canvas and choose how to use it. Imported bytes become part of the
document immediately, so moving or deleting the original image does not break
your face. Names are generated inside the exported face folder, with no absolute
paths or external references.

A background must match the canvas at 1x or 2x. Changing the canvas size requires
a matching background and enough room for every control. Supported button
sprite states are normal, hover, pressed, and disabled; import normal first.
Version 3 also supports the four corresponding playing states for the pause
artwork, and state sprites for popup seek and volume triggers.
Sprites are drawn within each button's logical rectangle, then rotated with the
button. Supply unrotated sprites to avoid applying an angle twice.

Version 3 can include a separate window mask. Its alpha channel clips the
complete face, including controls. Import a matching 1x or 2x PNG through the
Background panel, or remove the mask to use the background's own transparency.
If you change the canvas size, supply a matching mask or remove the old one.

The existing face limits apply: a 64 KiB manifest, 4 MiB per PNG, 16 MiB of
declared images per face, and image dimensions up to 2048 pixels. Undo retains
at most 100 steps and 64 MiB of unique PNG bytes across document snapshots.
The combined declared image dimensions must fit the 128 MiB decode
budget, preventing highly compressed images from exhausting memory.

## Rotated controls

Version 2 faces accept `controlRotations`, a map of control names to angles in
degrees. Positive angles rotate clockwise around the center of the logical
control rectangle. Angles range from -180 to 180; a missing angle means zero.
Buttons, sliders, labels, and the cover aperture can rotate. The window drag
region remains axis aligned.

```json
{
  "formatVersion": 2,
  "controls": { "play": [100, 200, 60, 48] },
  "controlRotations": { "play": -15 }
}
```

This is a fragment, not a complete face manifest. Versions 1 and 2 require the
full control set; version 3 permits omitted controls. Rotation applies to the
visual and its pointer interaction together. Its transformed footprint must
remain inside the canvas. Version 1/2 also requires it to stay clear of other
controls and the drag region. Use the editor's outline
and validation feedback to check the actual rotated footprint.

## Save and install

**Save As** writes an ordinary folder containing `face.json` and only its
declared PNG assets. Choose a new or empty folder outside your working face
folder. After saving, **Save** updates that working folder. **Export copy…**
writes another portable copy without moving the working document or marking
unsaved work as saved.

Save validates the complete staged snapshot before publishing it. Existing
folders and unrelated files are protected: if a working folder changes outside
the editor or gains additional files, reopen it or use Save As. If publishing
fails, the editor restores the previous folder. If restoration also fails, its
error identifies the recovery folder containing the original bytes.

Install an exported folder through **Install face…** in the player's face picker.
Installation still validates the same data-only format and does not overwrite a
face with an existing ID. Keep your editable working copy separately if you plan
to revise it after installation. See [Faces](faces.md) for the pack format.

## Verification on each platform

Run the editor on macOS and Linux, open a bundled template, and move, resize,
rotate, undo, and redo a button and slider. Confirm the preview follows the
handles and inspector values. Import a PNG, remove the source file, save to a
new folder, close the editor, and reopen that folder. Check that geometry,
typography, sprites, and angles survive unchanged. In a version 1/2 face, try
overlapping controls and confirm saving is blocked until the layout is valid.

On Linux, install the exported face in the player. Check click and keyboard
focus on angled buttons, drag both ends of an angled slider, and switch faces
while using the controls. Player actions retain their existing command guards;
editor preview controls do not send playback commands.
