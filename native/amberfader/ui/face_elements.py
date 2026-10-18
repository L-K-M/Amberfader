"""What the editor calls each face element, how it groups and draws them.

Element names are the manifest's control names plus "drag", the window drag
region. The sidebar lists them in groups:

    Playback   previous, play, next, like
    Screen     art, title, artists, time, playback, status
    Sliders    seek, volume
    Window     search, show, hide, menu, minimize, close, drag
"""
from __future__ import annotations

from ..face_document import BUTTONS, READOUTS, SPRITE_CONTROLS

DRAG = "drag"

LABELS = {
    "art": "Album Artwork",
    "title": "Track Title",
    "artists": "Artist and Album",
    "time": "Playback Time",
    "playback": "Playback State",
    "status": "Status Message",
    "previous": "Previous Track",
    "play": "Play / Pause",
    "next": "Next Track",
    "like": "Like",
    "seek": "Seek Slider",
    "volume": "Volume Slider",
    "search": "Search",
    "show": "Show YouTube Music",
    "hide": "Hide YouTube Music",
    "menu": "Menu",
    "minimize": "Minimize Window",
    "close": "Close Window",
    DRAG: "Window Drag Region",
}

GROUPS = (
    ("Playback", ("previous", "play", "next", "like")),
    ("Screen", ("art", "title", "artists", "time", "playback", "status")),
    ("Sliders", ("seek", "volume")),
    ("Window", ("search", "show", "hide", "menu", "minimize", "close", DRAG)),
)

# SF Symbols on macOS; other platforms fall back to a generic theme icon.
SYMBOLS = {
    "previous": "backward.end.fill",
    "play": "playpause.fill",
    "next": "forward.end.fill",
    "like": "heart",
    "art": "photo",
    "title": "textformat",
    "artists": "person",
    "time": "clock",
    "playback": "play.circle",
    "status": "info.circle",
    "seek": "slider.horizontal.below.rectangle",
    "volume": "speaker.wave.2",
    "search": "magnifyingglass",
    "show": "eye",
    "hide": "eye.slash",
    "menu": "line.3.horizontal",
    "minimize": "minus.square",
    "close": "xmark.square",
    DRAG: "hand.draw",
}

KINDS = {
    **{name: "Button" for name in BUTTONS},
    **{name: "Screen Text" for name in READOUTS},
    "art": "Artwork",
    "seek": "Slider",
    "volume": "Slider",
    DRAG: "Window Region",
}

# A new element's size, before it is clipped to the face.
DEFAULT_SIZES = {
    **{name: (48, 32) for name in BUTTONS},
    "art": (64, 64),
    "seek": (120, 16),
    "volume": (120, 16),
}
DEFAULT_READOUT_SIZE = (160, 28)

ADDABLE = tuple(name for _, names in GROUPS for name in names if name != DRAG)


def is_button(name: str) -> bool:
    return name in BUTTONS


def has_shape(name: str) -> bool:
    return name in BUTTONS or name == "art"


def can_hold_artwork(name: str, slider_style: str) -> bool:
    """Buttons always take sprites; sliders only in the popup style."""
    return name in BUTTONS or (name in SPRITE_CONTROLS and slider_style == "popup")


def ordered(names) -> list[str]:
    """Sidebar order for a set of element names."""
    present = set(names)
    return [name for _, group in GROUPS for name in group if name in present]
