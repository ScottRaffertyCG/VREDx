# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Property inspector: typed editors for the selected node's inputs.

Editors are generated from the NodeDef input metadata (type, uimin/uimax,
enum values, uifolder grouping).  Edits go through undoable
SetValueCommands; continuous slider drags merge into one undo step.
"""

import html
from functools import partial

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import commands, mtlx_types
from ..core.graph import can_expose_in_material
from .color_dialog import pick_color


class FloatSlider(QtWidgets.QWidget):
    """Slider + spinbox pair honoring uimin/uimax (soft range fallback)."""

    value_changed = QtCore.Signal(float)

    def __init__(self, lo, hi, parent=None):
        super().__init__(parent)
        self._lo, self._hi = lo, hi
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.slider.setRange(0, 1000)
        self.spin = QtWidgets.QDoubleSpinBox(self)
        self.spin.setDecimals(4)
        self.spin.setRange(-1e9, 1e9)
        self.spin.setSingleStep(max((hi - lo) / 100.0, 0.001))
        self.spin.setFixedWidth(78)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self._updating = False

    def set_value(self, value):
        self._updating = True
        self.spin.setValue(float(value))
        self._sync_slider(float(value))
        self._updating = False

    def _sync_slider(self, value):
        span = self._hi - self._lo
        if span > 0:
            t = max(0.0, min(1.0, (value - self._lo) / span))
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(t * 1000)))
            self.slider.blockSignals(False)

    def _from_slider(self, ticks):
        if self._updating:
            return
        value = self._lo + (self._hi - self._lo) * ticks / 1000.0
        self._updating = True
        self.spin.setValue(value)
        self._updating = False
        self.value_changed.emit(value)

    def _from_spin(self, value):
        if self._updating:
            return
        self._sync_slider(value)
        self.value_changed.emit(value)


class ColorButton(QtWidgets.QPushButton):
    """Swatch button opening a VRED-styled color picker (color3/color4)."""

    color_changed = QtCore.Signal(tuple)

    def __init__(self, channels=3, parent=None):
        super().__init__(parent)
        self.channels = channels
        self._value = tuple(0.0 for _ in range(channels))
        self.clicked.connect(self._pick)
        self.setFixedHeight(22)

    def set_value(self, value):
        value = tuple(value) if value else tuple(
            0.0 for _ in range(self.channels))
        self._value = value
        rgb = [int(max(0.0, min(1.0, c)) * 255) for c in value[:3]]
        self.setStyleSheet(
            "background-color: rgb(%d,%d,%d); color: %s;"
            " border: 1px solid #444448; border-radius: 3px;"
            " padding: 2px 6px;"
            % (rgb[0], rgb[1], rgb[2],
               "#111" if sum(rgb) > 382 else "#e0e0e0"))
        self.setText("%.3f, %.3f, %.3f" % value[:3] if len(value) >= 3
                     else str(value))

    def _pick(self):
        initial = QtGui.QColor.fromRgbF(
            *[max(0.0, min(1.0, c)) for c in self._value[:3]])
        parent = self.window()
        picked = pick_color(initial, parent)
        if picked is None:
            return
        value = picked
        if self.channels == 4:
            alpha = self._value[3] if len(self._value) > 3 else 1.0
            value = value + (alpha,)
        self.set_value(value)
        self.color_changed.emit(value)


class VectorEdit(QtWidgets.QWidget):
    """N spinboxes for vectorN / colorN typed as plain numbers."""

    value_changed = QtCore.Signal(tuple)

    def __init__(self, channels, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.spins = []
        for _ in range(channels):
            spin = QtWidgets.QDoubleSpinBox(self)
            spin.setDecimals(4)
            spin.setRange(-1e9, 1e9)
            spin.valueChanged.connect(self._emit)
            layout.addWidget(spin)
            self.spins.append(spin)
        self._updating = False

    def set_value(self, value):
        self._updating = True
        value = value or tuple(0.0 for _ in self.spins)
        for spin, component in zip(self.spins, value):
            spin.setValue(float(component))
        self._updating = False

    def _emit(self, _v):
        if not self._updating:
            self.value_changed.emit(
                tuple(s.value() for s in self.spins))


class FileEdit(QtWidgets.QWidget):
    """Line edit + browse button for filename inputs."""

    value_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QtWidgets.QLineEdit(self)
        button = QtWidgets.QPushButton("...", self)
        button.setFixedWidth(28)
        layout.addWidget(self.edit, 1)
        layout.addWidget(button)
        self.edit.editingFinished.connect(
            lambda: self.value_changed.emit(self.edit.text()))
        button.clicked.connect(self._browse)

    def set_value(self, value):
        self.edit.setText(str(value or ""))

    def _browse(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose texture", self.edit.text(),
            "Images (*.png *.jpg *.jpeg *.exr *.hdr *.tif *.tiff *.bmp);;"
            "All files (*)")
        if path:
            self.edit.setText(path)
            self.value_changed.emit(path)


class InspectorPanel(QtWidgets.QWidget):
    """Material settings and editors for the currently selected node."""

    def __init__(self, stack: commands.CommandStack, parent=None):
        super().__init__(parent)
        self.stack = stack
        self.graph = None
        self.node = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        material_box = QtWidgets.QGroupBox("Material", self)
        material_form = QtWidgets.QFormLayout(material_box)
        material_form.setContentsMargins(8, 8, 8, 8)
        material_form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.material_name = QtWidgets.QLineEdit(material_box)
        self.material_name.setPlaceholderText("Material name")
        self.material_name.editingFinished.connect(self._commit_material_name)
        material_form.addRow("Name", self.material_name)
        layout.addWidget(material_box)

        self.scroll = QtWidgets.QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        layout.addWidget(self.scroll, 1)

        self._placeholder()

    # --------------------------------------------------------------- public

    def set_material_name(self, name):
        """Sync the material name field without triggering edits."""
        self.material_name.blockSignals(True)
        self.material_name.setText(name or "")
        self.material_name.blockSignals(False)

    def show_node(self, graph, node):
        self.graph = graph
        if graph is not None:
            self.set_material_name(graph.name)
        self.node = node
        if node is None:
            self._placeholder()
            return
        container = QtWidgets.QWidget()
        container.setObjectName("VredXRoot")
        outer = QtWidgets.QVBoxLayout(container)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        name_row = QtWidgets.QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_label = QtWidgets.QLabel("<b>%s</b>" % html.escape(node.name))
        name_label.setTextFormat(QtCore.Qt.RichText)
        name_row.addWidget(name_label, 1)
        if can_expose_in_material(node, graph):
            expose = QtWidgets.QCheckBox("Expose in material")
            expose.setChecked(node.expose_in_material)
            expose.setToolTip(
                "Show this node in VRED's Realistic material editor.")
            expose.toggled.connect(self._commit_expose)
            name_row.addWidget(expose, 0, QtCore.Qt.AlignRight)
        name_widget = QtWidgets.QWidget()
        name_widget.setLayout(name_row)
        outer.addWidget(name_widget)

        subtitle = QtWidgets.QLabel(
            "<span style='color:#9a9a9f'>%s — %s</span>"
            % (html.escape(node.category), html.escape(node.nodedef.library)))
        subtitle.setTextFormat(QtCore.Qt.RichText)
        outer.addWidget(subtitle)
        if node.nodedef.doc:
            doc = QtWidgets.QLabel(node.nodedef.doc)
            doc.setWordWrap(True)
            doc.setStyleSheet("color: #9a9a9f;")
            outer.addWidget(doc)

        connected = {e.dst_input for e in graph.edges
                     if e.dst_node == node.name}

        folders = {}
        for idef in node.nodedef.inputs:
            folders.setdefault(idef.uifolder or "", []).append(idef)

        for folder, inputs in folders.items():
            box = QtWidgets.QGroupBox(folder or "Inputs", container)
            form = QtWidgets.QFormLayout(box)
            form.setLabelAlignment(QtCore.Qt.AlignRight)
            form.setContentsMargins(8, 4, 8, 8)
            for idef in inputs:
                label = idef.uiname or idef.name
                if idef.name in connected:
                    widget = QtWidgets.QLabel("(connected)")
                    widget.setStyleSheet("color: #7aa87a;")
                else:
                    widget = self._editor_for(idef)
                if idef.doc:
                    widget.setToolTip(idef.doc)
                form.addRow(label, widget)
            outer.addWidget(box)

        outer.addStretch(1)
        self.scroll.setWidget(container)

    # -------------------------------------------------------------- editors

    def _editor_for(self, idef):
        value = self.node.get_value(idef.name)
        type_name = idef.type

        if idef.enum_values:
            combo = QtWidgets.QComboBox()
            combo.addItems(list(idef.enum_values))
            if value in idef.enum_values:
                combo.setCurrentText(str(value))
            combo.currentTextChanged.connect(
                partial(self._commit, idef.name))
            return combo

        if type_name == "float":
            lo = _scalar(idef.uimin, _scalar(idef.uisoftmin, 0.0))
            hi = _scalar(idef.uimax, _scalar(idef.uisoftmax, 1.0))
            if hi <= lo:
                hi = lo + 1.0
            slider = FloatSlider(lo, hi)
            slider.set_value(value if value is not None else 0.0)
            slider.value_changed.connect(
                partial(self._commit_merged, idef.name))
            return slider

        if type_name == "integer":
            spin = QtWidgets.QSpinBox()
            spin.setRange(-10**9, 10**9)
            spin.setValue(int(value) if value is not None else 0)
            spin.valueChanged.connect(partial(self._commit, idef.name))
            return spin

        if type_name == "boolean":
            check = QtWidgets.QCheckBox()
            check.setChecked(bool(value))
            check.toggled.connect(partial(self._commit, idef.name))
            return check

        if type_name in ("color3", "color4"):
            button = ColorButton(mtlx_types.TUPLE_SIZES[type_name])
            button.set_value(value)
            button.color_changed.connect(partial(self._commit, idef.name))
            return button

        if type_name in ("vector2", "vector3", "vector4"):
            vec = VectorEdit(mtlx_types.TUPLE_SIZES[type_name])
            vec.set_value(value)
            vec.value_changed.connect(
                partial(self._commit_merged, idef.name))
            return vec

        if type_name == "filename":
            fedit = FileEdit()
            fedit.set_value(value)
            fedit.value_changed.connect(partial(self._commit, idef.name))
            return fedit

        if type_name in ("string", "geomname"):
            edit = QtWidgets.QLineEdit(str(value or ""))
            edit.editingFinished.connect(
                lambda e=edit, n=idef.name: self._commit(n, e.text()))
            return edit

        label = QtWidgets.QLabel("(%s)" % type_name)
        label.setStyleSheet("color: #808085;")
        return label

    # -------------------------------------------------------------- commits

    def _commit_material_name(self):
        name = self.material_name.text().strip()
        if self.graph is not None and name:
            self.graph.name = name

    def _commit(self, input_name, value):
        if self.node is None:
            return
        self.stack.push(commands.SetValueCommand(
            self.graph, self.node.name, input_name, value))

    def _commit_expose(self, exposed):
        if self.node is None:
            return
        self.stack.push(commands.SetExposeCommand(
            self.graph, self.node.name, exposed))

    def _commit_merged(self, input_name, value):
        if self.node is None:
            return
        self.stack.push(commands.SetValueCommand(
            self.graph, self.node.name, input_name, value), merge=True)

    # ----------------------------------------------------------------- misc

    def _placeholder(self):
        label = QtWidgets.QLabel("Select a node to edit its properties.")
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet("color: #8a8a8f;")
        self.scroll.setWidget(label)


def _scalar(value, fallback):
    if isinstance(value, (int, float)):
        return float(value)
    return fallback
