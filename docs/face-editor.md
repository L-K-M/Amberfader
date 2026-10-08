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

## The editor window

```
┌──────────────────────────── toolbar ────────────────────────────┐
│ [◧] [+ ▾]               [100% ▾] [#] [⬚]                   [◨] │
├─────────────┬─────────────────────────────────┬─────────────────┤
│ Elements    │              canvas             │ Element | Face  │
│ (sidebar)   │                                 │ inspector       │
├─────────────┴─────────────────────────────────┴─────────────────┤
│ messages                         ⚠ why the face cannot be saved │
└─────────────────────────────────────────────────────────────────┘
```

Each face opens in its own window with its own undo history, selection and
zoom. The **sidebar** lists the face's elements by group (Playback, Screen,
Sliders, Window); **+** adds a missing element and **−** removes the selected
one. The **inspector** has two panes: **Element** edits the selected element's
position, size, rotation, shape, screen text and button artwork; **Face** edits
the name, ID, author, size, fonts, background, window mask and colors.
Sections collapse with their disclosure arrows. The toolbar shows or hides the
sidebar and inspector, adds elements, sets the zoom, and turns on **Snap to
Grid** and **Guides** (element outlines and selection handles). Right-click the
toolbar to show icons, text, or both.

The status bar names the first problem that prevents saving, for example
“Play / Pause overlaps Next Track”. Click it to select that element. **Save**
stays available and explains the problem if you try.

## Create and edit

The editor opens with the **Face Gallery**. Choose a built-in face as a
template and click **Create** (or press Return), or switch to **Installed** to
open one of the player's faces for editing in place. Search with ⌘F. The
gallery returns with **File → New Face…** (⌘N), **File → Open Installed Face…**
(⇧⌘O) and **Window → Face Gallery**. **File → Open…** (⌘O) opens any face folder;
**Open Recent** lists the faces you opened or saved.

A template becomes an untitled copy with its own ID and name; the editor never
saves over the bundled artwork. Installed faces open in place: **Save** updates
the installed face, and the player uses the change the next time it loads that
face. You can also use **Face editor…** in the player's menu or **Edit a copy…**
in the face picker to start with that face. Until you change a copy, opening
another face reuses its window without asking to save it.

Select an element on the canvas or in the sidebar. Drag it to move it (Shift
keeps it on one axis), resize it with its corner handles, or rotate it with the
round handle (Shift snaps to 15°). Arrow keys move the selection by one pixel,
or ten with Shift; holding a key is one undo step. Delete removes the selected
element. Hold Space and drag, or scroll, to pan; pinch or ⌘-scroll to zoom.
Hold Option (Alt on Linux) to bypass **Snap to Grid** during a drag. Escape
cancels a drag in progress. Right-click an element for its commands.

Inspector fields work like other Mac inspectors: type a value and press Return
or Tab to apply it, or Escape to restore the previous value. Arrow keys step a
number, and Shift-arrow steps by 10. Color wells open the system color panel;
the face updates while you pick, and the whole pick is one undo step.

Undo and Redo name what they revert, such as **Undo Move** or **Undo Change
Accent Color**. While you type in a field, ⌘Z first undoes the typing, then
earlier changes to the face. A move, resize, or rotation gesture is one undo
step.

The face's drag region is editable too. Keep it clear of playback controls so
the player can distinguish a window drag from a control press. Screen labels,
buttons, artwork, and sliders must fit inside the canvas. Version 1/2 layouts
also require controls to avoid each other and the drag region. A draft preview
can show overlapping controls, or controls partly outside the face, while you
work; saving still requires a valid layout.

Per-screen font, size, alignment, bold and italic overrides use the same
rendering as the player and picker. You can also specify a font family and a
text color. Font families depend on what is installed on your computer.
**Use Face Defaults** removes an element's text overrides.

## Windows, quitting and recovery

On macOS the editor keeps running after you close its last window: the menu bar
still offers **New Face…** and **Open…**, and clicking the Dock icon shows the
gallery. Faces can be opened from Finder with **Open With** or by dropping a
face folder on the Dock icon. If an open face is already in a window, that
window comes forward. On Linux the editor quits with its last window.

Closing a window or quitting asks before discarding unsaved changes. The editor
also keeps a recovery copy of unsaved work in its application data folder,
separate from your face folders. If it quits unexpectedly, the next launch
reopens that work as unsaved. A recovered face stays attached to its folder only
if the folder has not changed since; **Undo Recover Changes** shows the saved
version. With macOS **Close windows when quitting an application** turned off,
faces that were open at quit reopen at the next launch.

## Import Audion faces

Choose **File → Import Audion Face…**, then **Browse folder…** or **Browse ZIP…**.
You can select a single converted Audion face folder, a collection of folders,
or a supported ZIP archive. Select a face in the list to preview its conversion;
the filter finds faces by name. The dialog shows the original credits and any
features that could not be converted. Review these notes before choosing
**Import editable copy**.

The import opens an unsaved Amberfader document. It reads the source without
changing or extracting files into it, and keeps the converted images inside
the document. Importing does not install the face or change the player. Use
**Save As** to create a portable face folder, then install it through the player.
Original source credits remain visible in the Face inspector and are included in
the saved manifest.

### Import a whole collection

Choose **File → Import Audion Collection…** and select a collection ZIP,
such as `Faces - 2021-01-05.zip` from [Panic's
downloads](https://download.panic.com/audion-viewer/) (856 faces). The editor
converts every face and installs it in your faces folder. A progress window
names each face; **Stop** ends the import and keeps the faces installed so far.
The summary counts installed faces and lists any that could not be converted.

Imported faces appear under **Installed** in the Face Gallery, ready to edit,
and in the player's **Faces** window. The gallery opens with the first of them
selected. Importing the same ZIP again skips the faces
it already installed. The open document is not changed. In testing, Panic's
856-face collection took about a minute and used about 260 MiB of disk space.
Up to 1024 installed faces load.

The importer supports Panic's preserved JSON/PNG format containing `index.json`
and its images. Original classic resource-fork and PICT files require conversion
to that format first.

Source ZIPs are limited to 512 MiB, 150,000 entries and 32 MiB of directory
metadata. A collection can contain up to 2048 faces; folder discovery scans up
to 8192 immediate entries. ZIP members must use stored or deflate compression.
Archives are read in place and are never extracted.

Imported version 3 faces can omit elements that the original design did not
contain. Use **Element → Add Element** (or **+** in the toolbar or sidebar) to
add a playback button, screen label, artwork aperture, or slider. Use
**Remove Element** or Delete to remove the selected control;
the window drag region remains required. Adding and removing elements can be
undone. Version 3 preserves small canvas dimensions and overlapping controls
used by these designs. Existing version 1 and 2 faces retain their layout rules;
removing a control upgrades that document to version 3.

Button artwork may already contain its labels. Turn off **Labels on button art**
in the Face inspector to keep the original artwork without drawing another
label over it. Imported sliders may use a popup control when their
original shape cannot be represented by a straight track.

On Flatpak, choose the containing folder so the native file picker can grant
access to the index and its images together. Selecting a ZIP grants access to
one self-contained source. If an image cannot be read, select the folder again
or choose an accessible archive. Unsupported or malformed sources leave your
current face intact.

## Backgrounds and sprites

Import a PNG background through the Face inspector or **Face → Import
Background…**, and button artwork through the Element inspector's **Artwork**
list or **Element → Import Artwork…**. You can also drop a PNG on the canvas:
dropped on a button, it becomes that button's normal artwork; anywhere else, it
becomes the background. The canvas names the target while you drag. **Remove**
in the Artwork list removes one state's artwork; removing Normal removes them
all. Imported bytes become part of the document immediately, so moving or deleting the original image does not break
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
Face inspector's Background section, or remove the mask to use the background's
own transparency.
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

**Save As…** (⇧⌘S) names a new folder in the save panel and writes
`face.json` and only its declared PNG assets into it. The folder must be new or
empty and outside your working face folder. After saving, **Save** (⌘S) updates
that folder, and **Revert to Saved** discards changes since. **Export Copy…**
(⇧⌘E) writes another portable copy without moving the working document or
marking unsaved work as saved. **Show in Finder** reveals the saved folder.

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
