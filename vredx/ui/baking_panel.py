# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""Texture baking panel with map selection, preview, and batch queue."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, List, Optional, Set

from PySide6 import QtCore, QtGui, QtWidgets

from ..baking.batch import BatchBaker, BatchEntry
from ..baking.engine import BakeEngine, BakeError, BakeResult
from ..baking.formats import RESOLUTION_PRESETS
from ..baking.maps import (
    BakeMap, DEFAULT_MAP_SLOTS, catalog_bake_maps,
    has_geometry_dependent_nodes, input_name_from_bake_filename,
)
from ..baking.mesh_bridge import (
    INSIDE_VRED, selected_geometry_meshes, uv_status_label,
)
from ..baking.naming import DEFAULT_TEMPLATE, FILENAME_TEMPLATE_TOOLTIP
from ..baking import runtime as bake_runtime
from ..core.graph import Graph
from .preview_panel import _PreviewSwatch, prepare_preview_image
from . import style


_PLACEHOLDER = "Bake to preview maps"
_CHECKBOX_STYLE = (
    "QCheckBox { color: #dcdce2; font-size: 11px;"
    " background: transparent; spacing: 6px; }"
    "QCheckBox::indicator { width: 13px; height: 13px; }")


def _section_frame(title: str, bg: str) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
    frame = QtWidgets.QFrame()
    frame.setObjectName("VredXBakingSection")
    frame.setStyleSheet(
        "QFrame#VredXBakingSection {"
        " background-color: %s; border: 1px solid #333338;"
        " border-radius: 6px; }" % bg)
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(10, 8, 10, 10)
    layout.setSpacing(6)
    if title:
        header = QtWidgets.QLabel(title)
        header.setStyleSheet(style.BAKING_TITLE_STYLE)
        layout.addWidget(header)
    body = QtWidgets.QVBoxLayout()
    body.setSpacing(4)
    layout.addLayout(body)
    return frame, body


def _field_label(text: str, parent=None) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text, parent)
    label.setStyleSheet(style.BAKING_LABEL_STYLE)
    return label


class _BatchLogPanel(QtWidgets.QWidget):
    """Side-by-side Batch / Log tabs with a shared collapsible body."""

    def __init__(self, bg: str, parent=None):
        super().__init__(parent)
        self._bg = bg
        self._active: Optional[str] = None
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        tabs_row = QtWidgets.QHBoxLayout()
        tabs_row.setSpacing(0)
        tab_style = (
            "QToolButton { color: #a0a0a8; font-weight: 600; font-size: 13px;"
            " background: %s; border: 1px solid #333338; padding: 8px 10px; }"
            "QToolButton:checked { background: #35353a; color: #ffffff; }"
            % bg)
        self._batch_tab = QtWidgets.QToolButton(self)
        self._batch_tab.setText("Batch")
        self._log_tab = QtWidgets.QToolButton(self)
        self._log_tab.setText("Log")
        for tab in (self._batch_tab, self._log_tab):
            tab.setCheckable(True)
            tab.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            tab.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding,
                QtWidgets.QSizePolicy.Fixed)
            tab.setStyleSheet(tab_style)
        self._batch_tab.clicked.connect(self._toggle_batch)
        self._log_tab.clicked.connect(self._toggle_log)
        tabs_row.addWidget(self._batch_tab, 1)
        tabs_row.addWidget(self._log_tab, 1)
        outer.addLayout(tabs_row)

        self._body = QtWidgets.QFrame(self)
        self._body.setObjectName("VredXBakingSection")
        self._body.setStyleSheet(
            "QFrame#VredXBakingSection {"
            " background-color: %s; border: 1px solid #333338;"
            " border-top: none; border-bottom-left-radius: 6px;"
            " border-bottom-right-radius: 6px; }" % bg)
        self._body.hide()
        body_layout = QtWidgets.QVBoxLayout(self._body)
        body_layout.setContentsMargins(10, 8, 10, 10)
        body_layout.setSpacing(6)
        self._stack = QtWidgets.QStackedWidget(self._body)
        body_layout.addWidget(self._stack)
        outer.addWidget(self._body)

        self.batch_page = QtWidgets.QWidget()
        self.log_page = QtWidgets.QWidget()
        self._stack.addWidget(self.batch_page)
        self._stack.addWidget(self.log_page)
        self.batch_layout = QtWidgets.QVBoxLayout(self.batch_page)
        self.batch_layout.setContentsMargins(0, 0, 0, 0)
        self.batch_layout.setSpacing(6)
        self.log_layout = QtWidgets.QVBoxLayout(self.log_page)
        self.log_layout.setContentsMargins(0, 0, 0, 0)
        self.log_layout.setSpacing(6)
        self._update_arrows()

    def _update_arrows(self):
        self._batch_tab.setArrowType(
            QtCore.Qt.DownArrow if self._active == "batch"
            else QtCore.Qt.RightArrow)
        self._log_tab.setArrowType(
            QtCore.Qt.DownArrow if self._active == "log"
            else QtCore.Qt.RightArrow)

    def _set_active(self, which: Optional[str]):
        self._active = which
        self._body.setVisible(which is not None)
        self._batch_tab.setChecked(which == "batch")
        self._log_tab.setChecked(which == "log")
        if which == "batch":
            self._stack.setCurrentWidget(self.batch_page)
        elif which == "log":
            self._stack.setCurrentWidget(self.log_page)
        self._update_arrows()

    def _toggle_batch(self):
        if self._active == "batch":
            self._set_active(None)
        else:
            self._set_active("batch")

    def _toggle_log(self):
        if self._active == "log":
            self._set_active(None)
        else:
            self._set_active("log")

    def show_batch(self):
        self._set_active("batch")

    def show_log(self):
        self._set_active("log")


class _MapSlotEditor(QtWidgets.QWidget):
    """Default map slots plus + menu to add more bake targets."""

    changed = QtCore.Signal()
    selection_changed = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._catalog: Dict[str, BakeMap] = {}
        self._slots: List[str] = []
        self._boxes: Dict[str, QtWidgets.QCheckBox] = {}
        self._block_selection_signal = False

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._add_btn: Optional[QtWidgets.QWidget] = None

    def set_add_button(self, button: QtWidgets.QWidget):
        self._add_btn = button
        button.clicked.connect(self._show_add_menu)
        self._update_add_enabled()

    def _update_add_enabled(self):
        if self._add_btn is not None:
            self._add_btn.setEnabled(bool(self._available_to_add()))

    def set_catalog(self, maps: List[BakeMap], *, reset_slots: bool = True):
        self._catalog = {m.input_name: m for m in maps}
        if reset_slots:
            self._slots = [
                name for name in DEFAULT_MAP_SLOTS if name in self._catalog]
            if not self._slots and self._catalog:
                self._slots = [sorted(self._catalog)[0]]
        else:
            self._slots = [n for n in self._slots if n in self._catalog]
        self._rebuild_rows()

    def _rebuild_rows(self):
        while self._layout.count() > 0:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._boxes.clear()

        if not self._slots:
            self.selection_changed.emit(False)
            self._update_add_enabled()
            return

        for name in self._slots:
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(4)
            box = QtWidgets.QCheckBox(name, self)
            box.setStyleSheet(_CHECKBOX_STYLE)
            box.setChecked(True)
            box.toggled.connect(self._on_box_toggled)
            self._boxes[name] = box
            row.addWidget(box, 1)
            remove = QtWidgets.QToolButton(self)
            remove.setText("×")
            remove.setFixedSize(22, 22)
            remove.setToolTip("Remove %s" % name)
            remove.clicked.connect(lambda _=False, n=name: self._remove_slot(n))
            row.addWidget(remove)
            wrap = QtWidgets.QWidget(self)
            wrap.setLayout(row)
            self._layout.addWidget(wrap)

        self._update_add_enabled()
        self._emit_selection_state()

    def _available_to_add(self) -> List[str]:
        return sorted(n for n in self._catalog if n not in self._slots)

    def _show_add_menu(self):
        available = self._available_to_add()
        if not available or self._add_btn is None:
            return
        menu = QtWidgets.QMenu(self)
        for name in available:
            action = menu.addAction(name)
            action.triggered.connect(
                lambda _=False, n=name: self._add_slot(n))
        menu.exec(self._add_btn.mapToGlobal(
            QtCore.QPoint(0, self._add_btn.height())))

    def _add_slot(self, name: str):
        if name in self._slots or name not in self._catalog:
            return
        self._slots.append(name)
        self._rebuild_rows()
        self.changed.emit()

    def _remove_slot(self, name: str):
        if name in self._slots:
            self._slots.remove(name)
            self._rebuild_rows()
            self.changed.emit()

    def _on_box_toggled(self, _checked):
        self.changed.emit()
        self._emit_selection_state()

    def _emit_selection_state(self):
        if self._block_selection_signal or not self._boxes:
            return
        all_on = all(b.isChecked() for b in self._boxes.values())
        self.selection_changed.emit(all_on)

    def selected(self) -> Set[str]:
        return {name for name, box in self._boxes.items() if box.isChecked()}

    def select_all(self, checked: bool = True):
        self._block_selection_signal = True
        for box in self._boxes.values():
            box.setChecked(checked)
        self._block_selection_signal = False
        self.changed.emit()
        self.selection_changed.emit(checked and bool(self._boxes))


class BakingPanel(QtWidgets.QWidget):
    """Flat UV 0-1 MaterialX texture baking controls."""

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._window = window
        self._last_result: Optional[BakeResult] = None
        self._last_baked_inputs: Set[str] = set()
        self._preview_images: Dict[str, QtGui.QImage] = {}
        self._batch_entries: List[BatchEntry] = []
        self._syncing_select_all = False

        self.setObjectName("VredXBakingPanel")
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), style.PANEL_BG)
        self.setPalette(palette)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: #2c2c2e; border: none; }"
            "QScrollBar:vertical { background: #232325; width: 10px; }"
            "QScrollBar::handle:vertical {"
            " background: #555560; min-height: 24px; border-radius: 4px; }")

        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background: #2c2c2e;")
        root = QtWidgets.QVBoxLayout(inner)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        source_frame, source_body = _section_frame(
            "Source", style.BAKING_BG_PRIMARY)
        self.source_label = QtWidgets.QLabel("", source_frame)
        self.source_label.setStyleSheet(style.BAKING_VALUE_STYLE)
        source_body.addWidget(self.source_label)
        root.addWidget(source_frame)

        maps_frame, maps_body = _section_frame(
            "Maps", style.BAKING_BG_SECONDARY)
        maps_header = QtWidgets.QHBoxLayout()
        maps_header.setSpacing(6)
        maps_header.setAlignment(QtCore.Qt.AlignVCenter)
        self.select_all_maps = QtWidgets.QCheckBox("", maps_frame)
        self.select_all_maps.setToolTip("Select or deselect all maps")
        self.select_all_maps.setChecked(True)
        self.select_all_maps.setStyleSheet(
            "QCheckBox { background: transparent; spacing: 0; }"
            "QCheckBox::indicator { width: 13px; height: 13px; }")
        self.select_all_maps.toggled.connect(self._on_select_all_maps)
        maps_header.addWidget(
            self.select_all_maps, 0, QtCore.Qt.AlignVCenter)
        maps_header.addStretch(1)
        self.add_map_btn = QtWidgets.QToolButton(maps_frame)
        self.add_map_btn.setText("+")
        self.add_map_btn.setToolTip("Add map…")
        self.add_map_btn.setFixedSize(24, 24)
        self.add_map_btn.setStyleSheet(
            "QToolButton { color: #dcdce2; font-size: 16px; font-weight: 600;"
            " background: #35353a; border: 1px solid #444448;"
            " border-radius: 4px; padding: 0; margin: 0; }"
            "QToolButton:hover { background: #404046; }"
            "QToolButton:disabled { color: #666670; background: #2a2a2e; }")
        maps_header.addWidget(self.add_map_btn, 0, QtCore.Qt.AlignVCenter)
        maps_body.addLayout(maps_header)
        self.map_slots = _MapSlotEditor(maps_frame)
        self.map_slots.set_add_button(self.add_map_btn)
        self.map_slots.selection_changed.connect(self._sync_select_all_maps)
        maps_body.addWidget(self.map_slots)
        root.addWidget(maps_frame)

        settings_frame, settings_body = _section_frame(
            "Settings", style.BAKING_BG_PRIMARY)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(_field_label("Resolution", settings_frame), 0, 0)
        self.resolution = QtWidgets.QComboBox(settings_frame)
        for res_label in RESOLUTION_PRESETS:
            self.resolution.addItem("%s px" % res_label, res_label)
        self.resolution.setCurrentIndex(3)
        grid.addWidget(self.resolution, 0, 1)
        grid.addWidget(_field_label("Format", settings_frame), 1, 0)
        self.format_combo = QtWidgets.QComboBox(settings_frame)
        self.format_combo.addItem("PNG", "png")
        self.format_combo.addItem("EXR", "exr")
        grid.addWidget(self.format_combo, 1, 1)
        grid.setColumnStretch(1, 1)
        settings_body.addLayout(grid)
        root.addWidget(settings_frame)

        output_frame, output_body = _section_frame(
            "Output", style.BAKING_BG_SECONDARY)
        output_body.addWidget(_field_label("Folder", output_frame))
        out_row = QtWidgets.QHBoxLayout()
        self.output_edit = QtWidgets.QLineEdit(output_frame)
        browse = QtWidgets.QPushButton("…", output_frame)
        browse.setFixedWidth(28)
        browse.setFixedHeight(24)
        browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(browse)
        output_body.addLayout(out_row)
        output_body.addWidget(_field_label("Filename template", output_frame))
        self.template_edit = QtWidgets.QLineEdit(DEFAULT_TEMPLATE, output_frame)
        self.template_edit.setToolTip(FILENAME_TEMPLATE_TOOLTIP)
        output_body.addWidget(self.template_edit)
        root.addWidget(output_frame)

        actions_frame = QtWidgets.QFrame()
        actions_frame.setObjectName("VredXBakingSection")
        actions_frame.setStyleSheet(
            "QFrame#VredXBakingSection {"
            " background-color: %s; border: 1px solid #333338;"
            " border-radius: 6px; }" % style.BAKING_BG_SECONDARY)
        actions_layout = QtWidgets.QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(8, 8, 8, 8)
        actions_layout.setSpacing(6)
        self.bake_btn = QtWidgets.QPushButton("Bake", actions_frame)
        self.bake_btn.clicked.connect(self._on_bake)
        self.batch_btn = QtWidgets.QPushButton("Batch Bake", actions_frame)
        self.batch_btn.clicked.connect(self._on_batch_bake)
        self.open_btn = QtWidgets.QPushButton("Open Folder", actions_frame)
        self.open_btn.clicked.connect(self._open_folder)
        actions_layout.addWidget(self.bake_btn)
        actions_layout.addWidget(self.batch_btn)
        actions_layout.addWidget(self.open_btn)
        root.addWidget(actions_frame)

        preview_frame, preview_body = _section_frame(
            "Bake Preview", style.BAKING_BG_PRIMARY)
        preview_pick = QtWidgets.QHBoxLayout()
        preview_pick.addWidget(_field_label("Map", preview_frame))
        self.map_combo = QtWidgets.QComboBox(preview_frame)
        self.map_combo.setEnabled(False)
        self.map_combo.currentTextChanged.connect(self._on_map_selected)
        preview_pick.addWidget(self.map_combo, 1)
        preview_body.addLayout(preview_pick)
        self.preview_swatch = _PreviewSwatch(preview_frame)
        self.preview_swatch.set_message(_PLACEHOLDER)
        preview_body.addWidget(self.preview_swatch, 0, QtCore.Qt.AlignHCenter)
        self.preview_label = QtWidgets.QLabel("", preview_frame)
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setStyleSheet(style.BAKING_MUTED_STYLE)
        preview_body.addWidget(self.preview_label)
        root.addWidget(preview_frame)

        self.batch_log = _BatchLogPanel(style.BAKING_BG_SECONDARY)
        self.batch_table = QtWidgets.QTableWidget(0, 4)
        self.batch_table.setHorizontalHeaderLabels(
            ["Mesh", "Material", "UV", "Output subdir"])
        self.batch_table.horizontalHeader().setStretchLastSection(True)
        self.batch_table.setMinimumHeight(100)
        batch_btns = QtWidgets.QHBoxLayout()
        add_sel = QtWidgets.QPushButton("Add Selection")
        add_sel.clicked.connect(self._add_selection_to_batch)
        remove_row = QtWidgets.QPushButton("Remove")
        remove_row.clicked.connect(self._remove_batch_row)
        batch_btns.addWidget(add_sel)
        batch_btns.addWidget(remove_row)
        batch_btns.addStretch(1)
        self.batch_log.batch_layout.addWidget(self.batch_table)
        self.batch_log.batch_layout.addLayout(batch_btns)

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMinimumHeight(100)
        self.log_view.setStyleSheet(style.BAKING_LOG_STYLE)
        log_btns = QtWidgets.QHBoxLayout()
        copy_log = QtWidgets.QPushButton("Copy")
        copy_log.setFixedWidth(52)
        copy_log.clicked.connect(self._copy_log)
        clear_log = QtWidgets.QPushButton("Clear")
        clear_log.setFixedWidth(52)
        clear_log.clicked.connect(self._clear_log)
        log_btns.addWidget(copy_log)
        log_btns.addWidget(clear_log)
        log_btns.addStretch(1)
        self.batch_log.log_layout.addWidget(self.log_view)
        self.batch_log.log_layout.addLayout(log_btns)
        root.addWidget(self.batch_log)

        root.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        footer = QtWidgets.QWidget(self)
        footer.setStyleSheet(
            "background: #2c2c2e; border-top: 1px solid #3a3a3e;")
        footer_layout = QtWidgets.QVBoxLayout(footer)
        footer_layout.setContentsMargins(6, 6, 6, 6)
        footer_layout.setSpacing(4)

        self.progress_label = QtWidgets.QLabel("", footer)
        self.progress_label.setStyleSheet(style.BAKING_MUTED_STYLE)
        self.progress_label.hide()
        footer_layout.addWidget(self.progress_label)

        self.progress_bar = QtWidgets.QProgressBar(footer)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        footer_layout.addWidget(self.progress_bar)

        self.status = QtWidgets.QLabel("", footer)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(style.BAKING_MUTED_STYLE)
        footer_layout.addWidget(self.status)
        outer.addWidget(footer)

        if not bake_runtime.is_runtime_available():
            self.bake_btn.setEnabled(False)
            self.batch_btn.setEnabled(False)
            self.status.setText(
                "Bake runtime missing. Maintainer: run "
                "scripts/fetch_materialx_baker.ps1, then reinstall VredX.")

        self.sync_from_graph()

    def sync_from_graph(self):
        graph = self._window.graph
        self.source_label.setText(graph.name or "Untitled")
        self._syncing_select_all = True
        self.map_slots.set_catalog(catalog_bake_maps(graph), reset_slots=True)
        self.select_all_maps.setChecked(True)
        self._syncing_select_all = False
        if not self.output_edit.text().strip():
            self.output_edit.setText(
                bake_runtime.default_bakes_dir(graph.name))

    def show_result(self, result: BakeResult, baked_inputs: Optional[Set[str]] = None):
        self._last_result = result
        if baked_inputs is not None:
            self._last_baked_inputs = set(baked_inputs)
        self._preview_images.clear()
        allowed = self._last_baked_inputs or set(result.images)
        paths: Dict[str, str] = {}

        for name, path in result.images.items():
            if path and os.path.isfile(path):
                paths[name] = path
        for name, path in result.previews.items():
            if path and os.path.isfile(path) and name not in paths:
                paths[name] = path

        if result.output_dir and os.path.isdir(result.output_dir):
            for fname in sorted(os.listdir(result.output_dir)):
                lower = fname.lower()
                if not (lower.endswith(".png") or lower.endswith(".exr")):
                    continue
                if fname.endswith("_preview.png"):
                    continue
                key = input_name_from_bake_filename(fname, allowed)
                if key and key not in paths:
                    full = os.path.join(result.output_dir, fname)
                    if os.path.isfile(full):
                        paths[key] = full

        for input_name, path in sorted(paths.items()):
            image = self._load_preview_image(path)
            if not image.isNull():
                self._preview_images[input_name] = prepare_preview_image(image)

        self.map_combo.blockSignals(True)
        self.map_combo.clear()
        if self._preview_images:
            self.map_combo.addItems(sorted(self._preview_images))
            self.map_combo.setEnabled(True)
            first = sorted(self._preview_images)[0]
            self.map_combo.setCurrentText(first)
            self._show_map(first)
        else:
            self.map_combo.setEnabled(False)
            self.preview_swatch.set_message("No preview images produced")
            self.preview_label.clear()
        self.map_combo.blockSignals(False)

    def _load_preview_image(self, path: str) -> QtGui.QImage:
        lower = path.lower()
        if lower.endswith(".exr"):
            preview = os.path.splitext(path)[0] + "_preview.png"
            if os.path.isfile(preview):
                return QtGui.QImage(preview)
            return QtGui.QImage()
        return QtGui.QImage(path)

    def _on_map_selected(self, input_name: str):
        if input_name:
            self._show_map(input_name)

    def _on_select_all_maps(self, checked: bool):
        if self._syncing_select_all:
            return
        self.map_slots.select_all(checked)

    def _sync_select_all_maps(self, all_checked: bool):
        if self._syncing_select_all:
            return
        self._syncing_select_all = True
        self.select_all_maps.setChecked(all_checked)
        self._syncing_select_all = False

    def _graph_for_bake(self) -> Graph:
        return self._window.graph

    def _selected_maps(self) -> Set[str]:
        selected = self.map_slots.selected()
        if not selected:
            raise BakeError("Select at least one map to bake.")
        return selected

    def _resolution(self) -> tuple[int, int]:
        key = self.resolution.currentData()
        return RESOLUTION_PRESETS.get(key, (2048, 2048))

    def _format(self) -> str:
        return self.format_combo.currentData()

    def _output_dir(self) -> str:
        path = self.output_edit.text().strip()
        if not path:
            path = bake_runtime.default_bakes_dir(self._window.graph.name)
            self.output_edit.setText(path)
        os.makedirs(path, exist_ok=True)
        return path

    def _browse_output(self):
        start = self.output_edit.text().strip() or os.path.expanduser("~")
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Bake output folder", start)
        if path:
            self.output_edit.setText(path)

    def _clear_log(self):
        self.log_view.clear()

    def _copy_log(self):
        text = self.log_view.toPlainText()
        if text:
            QtWidgets.QApplication.clipboard().setText(text)

    def _append_log(self, text: str):
        if not text:
            return
        self.batch_log.show_log()
        cursor = self.log_view.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text if text.endswith("\n") else text + "\n")
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _set_bake_busy(self, busy: bool, message: str = "",
                       progress: Optional[tuple[int, int]] = None):
        for btn in (self.bake_btn, self.batch_btn):
            btn.setEnabled(not busy and bake_runtime.is_runtime_available())
        self.open_btn.setEnabled(not busy)
        self.progress_label.setVisible(busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_label.setText(message)
            if progress:
                current, total = progress
                self.progress_bar.setRange(0, max(total, 1))
                self.progress_bar.setValue(current)
            else:
                self.progress_bar.setRange(0, 0)
        else:
            self.progress_label.clear()
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
        QtWidgets.QApplication.processEvents()

    def _on_bake(self):
        try:
            selected = self._selected_maps()
            width, height = self._resolution()
            graph = self._graph_for_bake()
            if has_geometry_dependent_nodes(graph):
                reply = QtWidgets.QMessageBox.warning(
                    self, "Geometry-dependent graph",
                    "This graph uses geometry-dependent nodes. Baked textures "
                    "may not match VRED shading. Continue?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No)
                if reply != QtWidgets.QMessageBox.Yes:
                    return

            self._set_bake_busy(True, "Writing MaterialX document…")
            engine = BakeEngine(
                pulse=lambda msg: self._set_bake_busy(True, msg),
                log=self._append_log,
            )
            result = engine.bake_graph(
                graph,
                self._output_dir(),
                width=width,
                height=height,
                fmt=self._format(),
                selected_inputs=selected,
                template=self.template_edit.text().strip() or DEFAULT_TEMPLATE,
            )
            self._last_baked_inputs = set(selected)
            self.show_result(result, baked_inputs=selected)
            msg = "Baked %d map(s)." % len(result.images)
            if result.warnings:
                msg += " " + "; ".join(result.warnings)
            self._append_log(msg + "\n")
            self.status.clear()
        except BakeError as exc:
            self._append_log("ERROR: %s\n" % exc)
            self.status.setText(str(exc).split("\n")[0])
            QtWidgets.QMessageBox.warning(self, "Bake failed", str(exc))
        finally:
            self._set_bake_busy(False)

    def _on_batch_bake(self):
        if not self._batch_entries:
            QtWidgets.QMessageBox.information(
                self, "Batch bake", "Add meshes to the batch list first.")
            return
        try:
            selected = self._selected_maps()
        except BakeError as exc:
            QtWidgets.QMessageBox.warning(self, "Batch bake", str(exc))
            return

        width, height = self._resolution()
        root = self._output_dir()

        def pulse(index, total, label):
            self._set_bake_busy(
                True, "Batch %d/%d: %s" % (index, total, label),
                progress=(index - 1, total))

        try:
            self._set_bake_busy(
                True, "Starting batch…",
                progress=(0, len(self._batch_entries)))
            baker = BatchBaker(pulse=pulse, log=self._append_log)
            batch = baker.run(
                self._batch_entries,
                root,
                width=width,
                height=height,
                fmt=self._format(),
                selected_inputs=selected,
                template=self.template_edit.text().strip() or DEFAULT_TEMPLATE,
            )
            if batch.results:
                self._last_baked_inputs = set(selected)
                self.show_result(batch.results[-1], baked_inputs=selected)
            if batch.errors:
                for err in batch.errors:
                    self._append_log("ERROR: %s\n" % err)
                self.status.setText(batch.errors[0])
            else:
                self._append_log(
                    "Batch complete: %d job(s).\n" % len(batch.results))
                self.status.clear()
        finally:
            self._set_bake_busy(False)

    def _add_selection_to_batch(self):
        if not INSIDE_VRED:
            QtWidgets.QMessageBox.information(
                self, "Batch bake",
                "Add from selection is available inside VRED only.")
            return
        meshes = selected_geometry_meshes()
        if not meshes:
            QtWidgets.QMessageBox.information(
                self, "Batch bake", "Select geometry nodes in the scene.")
            return
        graph = self._graph_for_bake()
        for mesh in meshes:
            entry = BatchEntry(
                mesh_name=mesh.name,
                material_name=mesh.material_name or graph.name,
                graph=graph,
                output_subdir="%s_%s" % (mesh.name, graph.name),
                uv_status=mesh.uv_status,
            )
            self._batch_entries.append(entry)
            row = self.batch_table.rowCount()
            self.batch_table.insertRow(row)
            self.batch_table.setItem(row, 0, QtWidgets.QTableWidgetItem(mesh.name))
            self.batch_table.setItem(
                row, 1, QtWidgets.QTableWidgetItem(entry.material_name))
            self.batch_table.setItem(
                row, 2,
                QtWidgets.QTableWidgetItem(uv_status_label(mesh.uv_status)))
            self.batch_table.setItem(
                row, 3,
                QtWidgets.QTableWidgetItem(entry.output_subdir))
        self.batch_log.show_batch()

    def _remove_batch_row(self):
        rows = sorted({i.row() for i in self.batch_table.selectedIndexes()},
                      reverse=True)
        for row in rows:
            self.batch_table.removeRow(row)
            if row < len(self._batch_entries):
                del self._batch_entries[row]

    def _open_folder(self):
        path = self._output_dir()
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", path])

    def _show_map(self, input_name: str):
        image = self._preview_images.get(input_name)
        if image is None:
            return
        self.preview_swatch.set_image(image)
        size = "%dx%d" % (image.width(), image.height())
        self.preview_label.setText("%s  ·  %s" % (input_name, size))
