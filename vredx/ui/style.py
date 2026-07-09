# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Colors, metrics and stylesheet for the VredX editor.

Kept in one module so the whole UI can be re-themed in one place.
Colors follow VRED's dark UI so the plugin feels native.
"""

import os

from PySide6 import QtGui

from .. import plugin_root

# ------------------------------------------------------------------- icons

ICON_DIR = os.path.join(plugin_root(), "resources", "icons")

LOGO_PATH = os.path.join(ICON_DIR, "vredx_logo.png")


def vredx_icon() -> QtGui.QIcon:
    """The VredX logo (MaterialX mark), used for windows and the module."""
    return QtGui.QIcon(LOGO_PATH)

# ------------------------------------------------------------------ canvas

CANVAS_BG = QtGui.QColor(38, 38, 40)
GRID_MINOR = QtGui.QColor(46, 46, 49)
GRID_MAJOR = QtGui.QColor(56, 56, 60)
GRID_STEP = 20
GRID_MAJOR_EVERY = 5

# ------------------------------------------------------------------- nodes

NODE_WIDTH = 190
NODE_HEADER_HEIGHT = 24
NODE_ROW_HEIGHT = 18
NODE_RADIUS = 6
NODE_BODY = QtGui.QColor(58, 58, 62)
NODE_BODY_SELECTED = QtGui.QColor(70, 70, 76)
NODE_BORDER = QtGui.QColor(24, 24, 26)
NODE_BORDER_SELECTED = QtGui.QColor(255, 160, 40)
NODE_TEXT = QtGui.QColor(225, 225, 225)
NODE_SUBTEXT = QtGui.QColor(160, 160, 165)
OPAQUE_NODE_BODY = QtGui.QColor(80, 52, 52)
COMPOUND_NODE_BODY = QtGui.QColor(52, 58, 72)
COMPOUND_NODE_BORDER = QtGui.QColor(120, 150, 210)
EXPORT_OUTPUT_NODE_BODY = QtGui.QColor(44, 68, 54)
EXPORT_OUTPUT_NODE_BORDER = QtGui.QColor(96, 190, 118)
EXPORT_OUTPUT_HEADER = QtGui.QColor(62, 128, 82)

# Header tint per MaterialX nodegroup.
GROUP_COLORS = {
    "material": QtGui.QColor(120, 60, 150),
    "pbr": QtGui.QColor(50, 100, 160),
    "shader": QtGui.QColor(50, 100, 160),
    "texture2d": QtGui.QColor(170, 110, 40),
    "texture3d": QtGui.QColor(170, 110, 40),
    "procedural": QtGui.QColor(150, 130, 40),
    "procedural2d": QtGui.QColor(150, 130, 40),
    "procedural3d": QtGui.QColor(150, 130, 40),
    "geometric": QtGui.QColor(60, 140, 90),
    "math": QtGui.QColor(90, 90, 100),
    "adjustment": QtGui.QColor(100, 140, 60),
    "compositing": QtGui.QColor(60, 130, 130),
    "conditional": QtGui.QColor(130, 70, 70),
    "channel": QtGui.QColor(110, 110, 60),
    "colortransform": QtGui.QColor(60, 110, 140),
    "convolution2d": QtGui.QColor(120, 90, 130),
    "npr": QtGui.QColor(160, 80, 120),
    "organization": QtGui.QColor(80, 80, 80),
    "application": QtGui.QColor(80, 80, 80),
    "unknown": QtGui.QColor(140, 60, 60),
}
GROUP_DEFAULT = QtGui.QColor(85, 85, 90)

# ------------------------------------------------------------------- ports

PORT_RADIUS = 5
PORT_BORDER = QtGui.QColor(20, 20, 22)
# Connection drag snaps to compatible pins within this scene distance (px).
SNAP_ACQUIRE = 48.0
SNAP_RING = QtGui.QColor(255, 200, 90)

# Port color per MaterialX type.
TYPE_COLORS = {
    "float": QtGui.QColor(160, 160, 160),
    "integer": QtGui.QColor(120, 150, 120),
    "boolean": QtGui.QColor(150, 100, 100),
    "color3": QtGui.QColor(230, 200, 60),
    "color4": QtGui.QColor(230, 170, 60),
    "vector2": QtGui.QColor(120, 170, 220),
    "vector3": QtGui.QColor(90, 140, 230),
    "vector4": QtGui.QColor(70, 110, 230),
    "matrix33": QtGui.QColor(150, 120, 200),
    "matrix44": QtGui.QColor(130, 100, 190),
    "string": QtGui.QColor(190, 130, 190),
    "filename": QtGui.QColor(210, 120, 160),
    "surfaceshader": QtGui.QColor(90, 200, 120),
    "displacementshader": QtGui.QColor(200, 140, 90),
    "volumeshader": QtGui.QColor(140, 200, 200),
    "lightshader": QtGui.QColor(240, 220, 130),
    "material": QtGui.QColor(190, 90, 220),
    "BSDF": QtGui.QColor(70, 180, 90),
    "EDF": QtGui.QColor(240, 200, 90),
    "VDF": QtGui.QColor(110, 190, 190),
}
TYPE_DEFAULT = QtGui.QColor(140, 140, 140)


def type_color(type_name):
    return TYPE_COLORS.get(type_name, TYPE_DEFAULT)


def group_color(group):
    return GROUP_COLORS.get(group, GROUP_DEFAULT)


# ------------------------------------------------------------------- edges

EDGE_COLOR = QtGui.QColor(170, 170, 175)
EDGE_SELECTED = QtGui.QColor(255, 160, 40)
EDGE_DRAG = QtGui.QColor(255, 200, 90)
EDGE_WIDTH = 2.0

# Panel chrome — matches WIDGET_QSS #VredXRoot background.
PANEL_BG = QtGui.QColor(44, 44, 46)

# Baking panel — alternating primary / secondary section backgrounds.
BAKING_BG_PRIMARY = "#2c2c2e"
BAKING_BG_SECONDARY = "#232325"

# Baking panel typography (section titles vs field labels vs values).
BAKING_TITLE_STYLE = (
    "color: #dcdce4; font-weight: 600; font-size: 13px;"
    " letter-spacing: 0.3px; background: transparent; border: none;")
BAKING_LABEL_STYLE = (
    "color: #909098; font-weight: 500; font-size: 11px;"
    " background: transparent;")
BAKING_VALUE_STYLE = (
    "color: #ececf0; font-weight: 400; font-size: 12px;"
    " background: transparent;")
BAKING_MUTED_STYLE = (
    "color: #808088; font-weight: 400; font-size: 11px;"
    " background: transparent;")
BAKING_MAP_BTN_STYLE = (
    "QPushButton { min-height: 22px; max-height: 24px;"
    " padding: 0 6px; font-size: 11px; font-weight: 500; }")
BAKING_LOG_STYLE = (
    "QPlainTextEdit { background: #1a1a1c; color: #c8c8d0;"
    " border: 1px solid #333338; font-family: Consolas, monospace;"
    " font-size: 11px; }")

# -------------------------------------------------------------- stylesheet

WIDGET_QSS = """
QWidget#VredXRoot, QDialog#VredXRoot {
    background: #2c2c2e; color: #e0e0e0;
}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background: #232325; color: #e0e0e0;
    border: 1px solid #1a1a1c; border-radius: 3px; padding: 2px 4px;
}
QTreeWidget, QListWidget, QTableWidget {
    background: #232325; color: #dddddd;
    border: 1px solid #1a1a1c; alternate-background-color: #28282a;
}
QGroupBox {
    border: 1px solid #444448; border-radius: 4px;
    margin-top: 8px; padding-top: 12px; color: #cccccc;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; }
QPushButton {
    background: #48484c; color: #e6e6e6;
    border: 1px solid #1c1c1e; border-radius: 3px; padding: 4px 12px;
}
QPushButton:hover { background: #56565c; }
QPushButton:pressed { background: #3a3a3e; }
QPushButton:disabled { color: #808080; }
QLabel { color: #d5d5d5; }
QToolTip { background: #1d1d1f; color: #e8e8e8; border: 1px solid #555; }
QSlider::groove:horizontal {
    background: #232325; height: 6px; border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #888890; width: 12px; margin: -4px 0; border-radius: 6px;
}
QSlider::groove:vertical {
    background: #232325; width: 6px; border-radius: 3px;
}
QSlider::handle:vertical {
    background: #888890; height: 12px; margin: 0 -4px; border-radius: 6px;
}
"""


def apply_vred_appearance(widget):
    """Copy palette/font from VRED's main window when embedded."""
    try:
        from ..vredbridge.ui_integration import vred_main_window
        window = vred_main_window()
    except Exception:
        window = None
    if window is None:
        return False
    widget.setPalette(window.palette())
    font = window.font()
    if not font.family().startswith("."):
        widget.setFont(font)
    return True
