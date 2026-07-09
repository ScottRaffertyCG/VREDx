# Created by Scott Rafferty @ Pyre Labs for use with the wider visualisation community.

"""VredX editor main widget.

Layout:  [menubar with send actions]
         [palette | node canvas | inspector/validation/scene tabs]

Built as a plain QWidget so it can be embedded in a VREDPluginWidget
(dockable script plugin panel) or shown as a floating window from the
Script Editor.
"""

import os

from typing import List

from PySide6 import QtCore, QtWidgets

from ..core import commands, validator
from ..core.graph import Graph
from ..core import mtlx_archive, mtlx_reader, mtlx_writer
from ..vredbridge import vred_api
from ..vredbridge.material_bridge import (
    BridgeError, MaterialBridge, default_document_path, is_writable_path,
)
from . import style
from .apply_progress import ApplyProgressDialog
from .canvas.scene import NodeGraphScene
from .canvas.view import NodeGraphView
from .graph_breadcrumb import GraphBreadcrumb
from .inspector import InspectorPanel
from .palette import PalettePanel
from .baking_panel import BakingPanel
from ..baking.runtime import is_runtime_available
from .preview_panel import PreviewPanel
from .validation_panel import ValidationPanel

from .. import plugin_root  # noqa: E402  (zip-safe resource location)

_PRESET_DIR = os.path.join(plugin_root(), "presets")
_EXAMPLE_DIR = os.path.join(plugin_root(), "examples")


class _MenubarCornerHeightSync(QtCore.QObject):
    """Keep the menu bar corner widget the same height as the menu bar."""

    def __init__(self, menubar, corner, parent=None):
        super().__init__(parent or menubar)
        self._menubar = menubar
        self._corner = corner
        QtCore.QTimer.singleShot(0, self._sync)

    def eventFilter(self, obj, event):
        if obj is self._menubar and event.type() == QtCore.QEvent.Resize:
            self._sync()
        return super().eventFilter(obj, event)

    def _sync(self):
        height = self._menubar.height()
        if height > 0:
            self._corner.setFixedHeight(height)


class VredXFloatingShell(QtWidgets.QMainWindow):
    """Top-level shell so the editor can be minimized like a normal window."""

    def __init__(self, editor):
        super().__init__(None)
        self._editor = editor
        self.setObjectName("VredXRoot")
        self.setWindowTitle(editor.windowTitle())
        self.setWindowIcon(editor.windowIcon())
        self.setMinimumSize(1100, 640)
        self.setCentralWidget(editor)
        style.apply_vred_appearance(self)


class VredXWindow(QtWidgets.QWidget):

    def __init__(self, library, parent=None, library_loader=None):
        super().__init__(parent)
        self.setObjectName("VredXRoot")
        self.setWindowTitle("VredX - MaterialX Editor")
        self.setWindowIcon(style.vredx_icon())
        self.setStyleSheet(style.WIDGET_QSS)
        style.apply_vred_appearance(self)

        self._library_loader = library_loader
        self._editor_ready = library is not None
        self._splitter = None
        self._right_panel = None
        self._canvas_widget = None
        self._menu_preview = None
        self._menu_attributes = None
        self._menu_palette = None
        self._menu_baking = None
        self.baking_panel = None
        self._baking_tab_index = None

        self.library = library
        self.graph = Graph("VredX_Material")
        self.stack = commands.CommandStack()
        self.bridge = MaterialBridge()
        self.current_path = None
        self._import_temp_dir = None
        self._dirty = False
        self._apply_busy = False
        self._apply_pending = False
        self._material_applied_once = False
        self._nav_stack: List[str] = []
        self._floating_shell = None
        self._docked_parent = None
        self._docked_layout = None

        self.inspector = InspectorPanel(self.stack, self)
        self.validation = ValidationPanel(self)
        self.preview_panel = PreviewPanel(self)

        if library is not None:
            self._create_canvas(library)
        else:
            self.scene = None
            self.view = None
            self.palette_panel = self._loading_widget(
                "Loading node definitions…")

        self._build_ui()
        if self._editor_ready:
            self._connect()
            self.new_document()

    def ensure_editor_ready(self):
        """Load MaterialX nodedef libraries on first use (deferred startup)."""
        if self._editor_ready:
            return
        if self._library_loader is None:
            raise RuntimeError("VredX editor has no library loader")
        self._activate_editor(self._library_loader())

    def _loading_widget(self, text):
        widget = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(widget)
        label = QtWidgets.QLabel(text, widget)
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet("color: #9a9a9f;")
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addStretch(1)
        return widget

    def _create_canvas(self, library):
        self.library = library
        self.scene = NodeGraphScene(self.graph, self.stack, library, self)
        self.view = NodeGraphView(self.scene, self)
        self.palette_panel = PalettePanel(library, self)

    def _activate_editor(self, library):
        if self._editor_ready:
            return
        self._editor_ready = True
        self._create_canvas(library)
        if self._splitter is not None:
            self._splitter.replaceWidget(0, self.palette_panel)
            if self._canvas_widget is not None and self.view is not None:
                layout = self._canvas_widget.layout()
                if layout.count() >= 2:
                    old = layout.itemAt(1).widget()
                    if old is not None and old is not self.view:
                        layout.replaceWidget(old, self.view)
                        old.deleteLater()
                elif layout.count() == 1:
                    layout.addWidget(self.view, 1)
            else:
                self._splitter.replaceWidget(1, self.view)
        self._connect()
        self.new_document()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._editor_ready and self._library_loader:
            self.ensure_editor_ready()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        self._menubar = self._build_menubar()
        root.addWidget(self._menubar)

        # ---- main splitter
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        self._splitter = splitter
        splitter.addWidget(self.palette_panel)
        canvas = QtWidgets.QWidget(self)
        self._canvas_widget = canvas
        canvas_layout = QtWidgets.QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(2)
        self.breadcrumb = GraphBreadcrumb(canvas)
        self.breadcrumb.sync_font_from_menubar(self._menubar)
        canvas_layout.addWidget(self.breadcrumb)
        if self.view is not None:
            canvas_layout.addWidget(self.view, 1)
        else:
            canvas_layout.addWidget(self._loading_widget(
                "Node canvas will appear after libraries load."), 1)
        splitter.addWidget(canvas)

        self._right_panel = QtWidgets.QWidget(self)
        right_layout = QtWidgets.QVBoxLayout(self._right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(self.preview_panel)

        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.addTab(self.inspector, "Inspector")
        self.tabs.addTab(self.validation, "Validation")
        self.scene_panel = SceneMaterialsPanel(self.bridge, self)
        self.tabs.addTab(self.scene_panel, "Scene")
        if is_runtime_available():
            self.baking_panel = BakingPanel(self)
            self._baking_tab_index = self.tabs.addTab(
                self.baking_panel, "Baking")
        self.tabs.currentChanged.connect(self._on_attributes_tab_changed)
        right_layout.addWidget(self.tabs, 1)

        splitter.addWidget(self._right_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([220, 700, 300])
        root.addWidget(splitter, 1)

        # ---- status
        self.status = QtWidgets.QLabel(self)
        self.status.setStyleSheet("color: #9a9a9f;")
        root.addWidget(self.status)

        if not vred_api.INSIDE_VRED:
            self.send_button.setEnabled(False)
            self.send_apply_button.setEnabled(False)
            self.auto_apply.setEnabled(False)
            tip = "Available inside VRED only"
            self.send_button.setToolTip(tip)
            self.send_apply_button.setToolTip(tip)

    def _build_menubar(self):
        menubar = QtWidgets.QMenuBar(self)

        file_menu = menubar.addMenu("&File")
        file_menu.addAction("&New", self.new_document,
                            "Ctrl+N")
        file_menu.addAction("&Open...", self.open_dialog,
                            "Ctrl+O")
        file_menu.addSeparator()
        file_menu.addAction("&Save", self.save, "Ctrl+S")
        file_menu.addAction("Save &As...", self.save_as,
                            "Ctrl+Shift+S")

        edit_menu = menubar.addMenu("&Edit")
        self._action_undo = edit_menu.addAction("&Undo", self._undo, "Ctrl+Z")
        self._action_redo = edit_menu.addAction("&Redo", self._redo, "Ctrl+Y")
        edit_menu.addSeparator()
        edit_menu.addAction("&Duplicate", self._duplicate_selected,
                            "Ctrl+D")
        edit_menu.addAction("&Delete", self._delete_selected, "Del")
        edit_menu.addSeparator()
        edit_menu.addAction("&Validate", self.run_validation, "Ctrl+Shift+V")

        create_menu = menubar.addMenu("&Create")
        presets = self._folder_menu(_PRESET_DIR, "(no presets found)")
        presets.setTitle("Presets")
        create_menu.addMenu(presets)
        examples = self._folder_menu(_EXAMPLE_DIR, "(no examples found)")
        examples.setTitle("Examples")
        create_menu.addMenu(examples)
        create_menu.addSeparator()
        create_menu.addAction("Add &Node...", self._quick_add_node, "Tab")

        selection_menu = menubar.addMenu("&Selection")
        selection_menu.addAction("Send to &VRED", self.send_to_vred)
        selection_menu.addAction("Send && Apply to Selection",
                                 self.send_and_apply_to_vred)
        selection_menu.addSeparator()
        selection_menu.addAction("Fit &View", self._fit_view, "F")

        window_menu = menubar.addMenu("&Window")
        self._menu_palette = window_menu.addAction("Node &List")
        self._menu_palette.setCheckable(True)
        self._menu_palette.setChecked(True)
        self._menu_palette.toggled.connect(self._toggle_palette)
        self._menu_preview = window_menu.addAction("&Preview")
        self._menu_preview.setCheckable(True)
        self._menu_preview.setChecked(True)
        self._menu_preview.toggled.connect(self._toggle_preview)
        self._menu_attributes = window_menu.addAction("&Attributes")
        self._menu_attributes.setCheckable(True)
        self._menu_attributes.setChecked(True)
        self._menu_attributes.toggled.connect(self._toggle_attributes)
        if is_runtime_available():
            self._menu_baking = window_menu.addAction("&Baking")
            self._menu_baking.setCheckable(True)
            self._menu_baking.setChecked(False)
            self._menu_baking.toggled.connect(self._toggle_baking)
        window_menu.addSeparator()
        self._menu_pop_out = window_menu.addAction("Pop &Out Editor")
        self._menu_pop_out.triggered.connect(self._pop_out_editor)
        self._menu_dock = window_menu.addAction("Dock Editor")
        self._menu_dock.triggered.connect(self._dock_editor)
        self._menu_dock.setEnabled(False)

        self._add_menubar_actions(menubar)
        return menubar

    def _add_menubar_actions(self, menubar):
        """Compact send controls on the right of the menu bar row."""
        corner = QtWidgets.QWidget(menubar)
        corner.setObjectName("VredXMenuBarActions")
        corner.setStyleSheet("""
            #VredXMenuBarActions QPushButton {
                padding: 0px 8px; font-size: 11px; min-height: 0px;
            }
            #VredXMenuBarActions QCheckBox {
                font-size: 11px; spacing: 4px; padding: 0px 2px;
            }
            #VredXMenuBarActions QCheckBox::indicator {
                width: 14px; height: 14px;
            }
        """)
        layout = QtWidgets.QHBoxLayout(corner)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(3)

        self.auto_apply = QtWidgets.QCheckBox("Auto Update", corner)
        self.auto_apply.setToolTip(
            "Re-send the material to VRED after you stop editing "
            "(debounced; compiling may take a few seconds)")
        layout.addWidget(self.auto_apply)

        self.send_button = QtWidgets.QPushButton("Send to VRED", corner)
        self.send_button.setToolTip(
            "Write the .mtlx document and compile it as a VRED "
            "MaterialX material")
        self.send_button.clicked.connect(self.send_to_vred)
        layout.addWidget(self.send_button)

        self.send_apply_button = QtWidgets.QPushButton("Send && Apply", corner)
        self.send_apply_button.setToolTip(
            "Send to VRED and assign the material to the selected "
            "scene geometry")
        self.send_apply_button.clicked.connect(self.send_and_apply_to_vred)
        layout.addWidget(self.send_apply_button)

        expand = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        for widget in (self.auto_apply, self.send_button, self.send_apply_button):
            widget.setSizePolicy(expand)

        menubar.setCornerWidget(corner, QtCore.Qt.TopRightCorner)
        menubar.installEventFilter(
            _MenubarCornerHeightSync(menubar, corner))

    def _folder_menu(self, folder, empty_label):
        menu = QtWidgets.QMenu(self)
        if os.path.isdir(folder):
            for filename in sorted(os.listdir(folder)):
                if not filename.endswith(".mtlx"):
                    continue
                path = os.path.join(folder, filename)
                label = os.path.splitext(filename)[0].replace("_", " ")
                action = menu.addAction(label)
                action.triggered.connect(
                    lambda checked=False, p=path: self.open_document(p))
        if menu.isEmpty():
            menu.addAction(empty_label).setEnabled(False)
        return menu

    def _connect(self):
        self._inspector_selection = []
        self.scene.selectionChanged.connect(self._on_selection)
        self.scene.graph_changed.connect(self._on_graph_changed)
        self.scene.node_double_clicked.connect(self._on_node_double_clicked)
        self.scene.create_compound_requested.connect(
            self._create_compound_from_selection)
        self.scene.add_graph_output_requested.connect(
            self._add_graph_output_for_node)
        self.scene.dissolve_compound_requested.connect(
            self._dissolve_compound)
        self.inspector.set_dissolve_callback(self._dissolve_compound)
        self.breadcrumb.navigated.connect(self._navigate_to_scope)
        self.palette_panel.add_requested.connect(self._add_from_palette)
        self.validation.issue_selected.connect(self._select_node)

        self._validate_timer = QtCore.QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(300)
        self._validate_timer.timeout.connect(self.run_validation)

        self._apply_timer = QtCore.QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(900)
        self._apply_timer.timeout.connect(self._auto_apply_now)

        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(400)
        self._preview_timer.timeout.connect(self._deferred_preview)
        self._preview_material = None
        self._preview_pending = False

        self._preview_pull_timer = QtCore.QTimer(self)
        self._preview_pull_timer.setSingleShot(True)
        self._preview_pull_timer.setInterval(800)
        self._preview_pull_timer.timeout.connect(self._pull_preview)

        if vred_api.INSIDE_VRED:
            try:
                vred_api.vrMaterialService.previewsChanged.connect(
                    self._on_previews_changed)
            except AttributeError:
                pass

    # ------------------------------------------------------------ document

    def new_document(self):
        self.ensure_editor_ready()
        graph = Graph("VredX_Material")
        # Seed with a standard surface + material output.
        ss_def = self.library.find_variant("standard_surface",
                                           "surfaceshader")
        sm_def = self.library.find_variant("surfacematerial", "material")
        if ss_def and sm_def:
            surface = graph.add_node(ss_def, "surface", (0.0, 0.0))
            material = graph.add_node(sm_def, "VredX_Material", (330.0, 0.0))
            graph.connect(surface.name, "out", material.name,
                          "surfaceshader")
        self._set_graph(graph, path=None)

    def open_dialog(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open MaterialX document", "",
            "MaterialX and archives (*.mtlx *.zip);;"
            "MaterialX (*.mtlx);;"
            "Zip archives (*.zip);;"
            "All files (*)")
        if path:
            self.open_document(path)

    def _pick_archive_member(self, archive_path, members):
        """Ask which .mtlx to open when a zip contains several candidates."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Choose MaterialX document")
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel(
            "This archive contains multiple MaterialX files.\n"
            "Choose which one to open:",
            dialog))
        list_widget = QtWidgets.QListWidget(dialog)
        for member in members:
            list_widget.addItem(member)
        list_widget.setCurrentRow(0)
        layout.addWidget(list_widget, 1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        item = list_widget.currentItem()
        return item.text() if item is not None else None

    def _cleanup_import_temp(self, temp_root=None):
        if temp_root is None:
            temp_root = self._import_temp_dir
        mtlx_archive.remove_extract_dir(temp_root or "")
        if temp_root is None or temp_root == self._import_temp_dir:
            self._import_temp_dir = None

    def open_document(self, path):
        self.ensure_editor_ready()
        archive_member = None
        if mtlx_archive.is_zip_path(path):
            try:
                members = mtlx_archive.list_mtlx_members(path)
            except (OSError, mtlx_archive.ArchiveError) as exc:
                QtWidgets.QMessageBox.critical(
                    self, "VredX", "Could not read archive:\n%s" % exc)
                return
            if not members:
                QtWidgets.QMessageBox.critical(
                    self, "VredX",
                    "No .mtlx file found in archive:\n%s" % path)
                return
            if len(members) > 1 and mtlx_archive.needs_member_choice(members):
                archive_member = self._pick_archive_member(path, members)
                if archive_member is None:
                    return
        try:
            result = mtlx_reader.load_document(
                path, self.library, archive_member=archive_member)
        except (mtlx_archive.ArchiveError, OSError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(
                self, "VredX", "Could not open document:\n%s" % exc)
            return
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "VredX", "Could not open document:\n%s" % exc)
            return
        self._cleanup_import_temp()
        if result.graph.temp_extract_dir:
            self._import_temp_dir = result.graph.temp_extract_dir
        loaded_path = result.graph.source_mtlx_path or path
        if mtlx_archive.is_zip_path(path):
            save_path = default_document_path(
                self.bridge.output_dir, result.graph.name)
            redirected = True
        else:
            save_path = self._document_save_path(result.graph, loaded_path)
            redirected = (
                os.path.normcase(os.path.abspath(save_path))
                != os.path.normcase(os.path.abspath(loaded_path)))
        self._set_graph(result.graph, save_path)
        if redirected:
            self._dirty = True
        if mtlx_archive.is_zip_path(path):
            self.status.setText(
                "Opened from archive; save will write to Documents/VredX.")
        self.view.fit_all()

    def _document_save_path(self, graph, source_path):
        """Writable save target; presets redirect to the user Documents folder."""
        if source_path and is_writable_path(source_path):
            return source_path
        return default_document_path(self.bridge.output_dir, graph.name)

    def save(self):
        if self.current_path is None or not is_writable_path(self.current_path):
            self.save_as()
            return
        try:
            os.makedirs(os.path.dirname(self.current_path), exist_ok=True)
            mtlx_writer.save_document(self.graph, self.current_path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self, "VredX", "Save failed:\n%s" % exc)
            return
        self._dirty = False
        self.status.setText("Saved %s" % self.current_path)

    def save_as(self):
        start = self.current_path
        if start is None or not is_writable_path(start):
            start = default_document_path(
                self.bridge.output_dir, self.graph.name)
        path, _f = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save MaterialX document", start,
            "MaterialX (*.mtlx)")
        if not path:
            return
        self.current_path = path
        self.save()

    def _set_graph(self, graph, path):
        prior = self._selection_snapshot()
        self.graph = graph
        self.current_path = path
        self._reset_navigation()
        self.scene.set_graph(graph)
        self.inspector.set_material_name(graph.name)
        self._dirty = False
        result = self.run_validation()
        self._sync_document_status(result)
        self.view.fit_all()
        self._refresh_inspector_after_graph_change(prior)
        if hasattr(self, "baking_panel") and self.baking_panel is not None:
            self.baking_panel.sync_from_graph()

    def _reset_navigation(self):
        self._nav_stack = []
        if self.scene is not None:
            self.scene.set_active_scope(None)
        self._update_breadcrumb()

    def _update_breadcrumb(self):
        segments = [(self.graph.name or "Material", None)]
        for compound_name in self._nav_stack:
            segments.append((compound_name, compound_name))
        self.breadcrumb.set_path(segments)

    def _navigate_into(self, compound_name: str):
        node = self.graph.nodes.get(compound_name)
        if node is None or not node.is_compound:
            return
        self._nav_stack.append(compound_name)
        self.scene.set_active_scope(compound_name)
        self._update_breadcrumb()
        self.scene.clearSelection()
        self._inspector_selection = []
        self.inspector.show_selection(
            self.graph, [], active_scope=self.scene.active_scope)
        self.view.fit_all()

    def _navigate_to_scope(self, scope):
        if scope is None:
            self._nav_stack = []
        else:
            try:
                index = self._nav_stack.index(scope) + 1
            except ValueError:
                return
            self._nav_stack = self._nav_stack[:index]
        self.scene.set_active_scope(
            self._nav_stack[-1] if self._nav_stack else None)
        self._update_breadcrumb()
        self.scene.clearSelection()
        self._inspector_selection = []
        self.inspector.show_selection(
            self.graph, [], active_scope=self.scene.active_scope)
        self.view.fit_all()

    def _sync_document_status(self, result):
        """Refresh the status bar after loading a preset or document."""
        if result.warnings:
            self.status.setText("%d warning(s); see Validation."
                                % len(result.warnings))
        elif not result.ok:
            self.status.setText("Validation failed; see Validation tab.")
        else:
            self.status.clear()

    def _selection_snapshot(self):
        names = self.scene.selected_node_names()
        node = self.graph.nodes.get(names[0]) if names else None
        return {
            "names": names,
            "category": node.category if node else None,
            "nodedef": node.nodedef.name if node else None,
        }

    def _refresh_inspector_after_graph_change(self, prior):
        """Keep the inspector in sync after preset/open/new document."""
        selected = [self.graph.nodes[n] for n in (prior.get("names") or [])
                    if n in self.graph.nodes]
        node = None
        if selected:
            node = selected[0]
        else:
            for name in prior.get("names") or []:
                candidate = self.graph.nodes.get(name)
                if candidate is not None:
                    node = candidate
                    break
            if node is None and prior.get("category"):
                for candidate in self.graph.nodes.values():
                    if candidate.category == prior["category"]:
                        node = candidate
                        break
            if node is None and prior.get("nodedef"):
                for candidate in self.graph.nodes.values():
                    if candidate.nodedef.name == prior["nodedef"]:
                        node = candidate
                        break
            if node is None and prior.get("names"):
                for category in ("standard_surface", "open_pbr_surface",
                                 "UsdPreviewSurface", "gltf_pbr",
                                 "disney_principled"):
                    for candidate in self.graph.nodes.values():
                        if candidate.category == category:
                            node = candidate
                            break
                    if node is not None:
                        break
            selected = [node] if node is not None else []
        self._inspector_selection = sorted(n.name for n in selected)
        self.inspector.show_selection(
            self.graph, selected, active_scope=self.scene.active_scope)
        if selected:
            self.scene.clearSelection()
            for n in selected:
                item = self.scene.node_items.get(n.name)
                if item is not None:
                    item.setSelected(True)

    # -------------------------------------------------------------- VRED

    def send_to_vred(self):
        self._send_to_vred(assign_to_selection=False)

    def send_and_apply_to_vred(self):
        self._send_to_vred(assign_to_selection=True)

    def _send_to_vred(self, assign_to_selection=False):
        result = self.run_validation()
        if not result.ok:
            self.tabs.setCurrentWidget(self.validation)
            self.status.setText(
                "Fix validation errors before sending to VRED.")
            return
        self._start_apply(manual=True, assign_to_selection=assign_to_selection)

    def _auto_apply_now(self):
        if not (self.auto_apply.isChecked() and vred_api.INSIDE_VRED):
            return
        if self._apply_busy:
            self._apply_pending = True
            return
        result = validator.validate(self.graph, self.library)
        if result.ok:
            self._start_apply(manual=False)

    def _start_apply(self, manual=False, assign_to_selection=False):
        if self._apply_busy:
            self._apply_pending = True
            return
        if not vred_api.INSIDE_VRED:
            return

        self._apply_busy = True
        self._apply_pending = False
        self._preview_timer.stop()
        self.send_button.setEnabled(False)
        self.send_apply_button.setEnabled(False)
        self.auto_apply.setEnabled(False)

        progress = None
        preview_material = None
        try:
            if manual:
                progress = ApplyProgressDialog(self)
                progress.show()
            material, path = self.bridge.apply_graph(
                self.graph, pulse=progress.pulse if progress else None)
            assigned = 0
            if assign_to_selection and material is not None:
                assigned = self.bridge.assign_to_selection(material)
        except (BridgeError, RuntimeError) as exc:
            if progress is not None:
                progress.close()
            if manual:
                QtWidgets.QMessageBox.critical(self, "VredX", str(exc))
            else:
                self.status.setText("Auto Update failed: %s" % exc)
        else:
            preview_material = material
            self._material_applied_once = True
            if manual and not self.auto_apply.isChecked():
                self.auto_apply.setChecked(True)
            if manual:
                if assign_to_selection:
                    if assigned:
                        self.status.setText(
                            "Sent '%s' and applied to %d node(s) (%s)"
                            % (self.graph.name, assigned, path))
                    else:
                        self.status.setText(
                            "Sent '%s' (%s) — no geometry selected"
                            % (self.graph.name, path))
                else:
                    self.status.setText("Sent '%s' to VRED (%s)"
                                        % (self.graph.name, path))
            else:
                self.status.setText("Auto-sent '%s'" % self.graph.name)
            self.scene_panel.refresh()
        finally:
            if progress is not None:
                progress.close()
            self._apply_busy = False
            self.send_button.setEnabled(True)
            self.send_apply_button.setEnabled(True)
            self.auto_apply.setEnabled(True)
            if preview_material is not None:
                self._schedule_preview(preview_material)
            if self._apply_pending:
                self._apply_pending = False
                QtCore.QTimer.singleShot(0, self._auto_apply_now)

    # ----------------------------------------------------------- preview

    def _schedule_preview(self, material):
        if not vred_api.INSIDE_VRED or material is None:
            return
        self._preview_material = material
        self._preview_timer.stop()
        self._preview_timer.start()

    def _deferred_preview(self):
        if self._preview_material is not None:
            self._run_preview(self._preview_material)

    def _run_preview(self, material):
        if not vred_api.INSIDE_VRED:
            return
        self._preview_pending = True
        self.preview_panel.set_refreshing()
        self.bridge.request_preview(material)
        self._preview_pull_timer.start()

    def _after_apply(self, material):
        """Legacy hook — prefer _schedule_preview."""
        self._schedule_preview(material)

    def _on_previews_changed(self):
        if self._preview_pending:
            self._pull_preview()

    def _pull_preview(self):
        if not vred_api.INSIDE_VRED:
            return
        image = self.bridge.capture_preview()
        if image is not None:
            self._preview_pending = False
            self.preview_panel.show_image(image)

    # --------------------------------------------------------------- misc

    def run_validation(self):
        result = validator.validate(self.graph, self.library)
        self.validation.show_result(result)
        return result

    def _on_graph_changed(self):
        self._dirty = True
        self._validate_timer.start()
        if self.auto_apply.isChecked():
            self._apply_timer.start()
        # Do not rebuild the inspector here: slider drags fire graph_changed
        # on every tick; destroying/recreating editor widgets mid-drag has
        # caused VRED crashes when the material is live on geometry.
        self.inspector.sync_expose_checkbox()

    def _on_selection(self):
        names = sorted(self.scene.selected_node_names())
        if names == self._inspector_selection:
            return
        self._inspector_selection = names
        nodes = [self.graph.nodes[n] for n in names if n in self.graph.nodes]
        self.inspector.show_selection(
            self.graph, nodes, active_scope=self.scene.active_scope)

    def _on_node_double_clicked(self, node_name):
        node = self.graph.nodes.get(node_name)
        if node is not None and node.is_compound:
            self._navigate_into(node_name)
            return
        self._focus_inspector(node_name)

    def _focus_inspector(self, node_name):
        self.tabs.setCurrentWidget(self.inspector)
        node = self.graph.nodes.get(node_name)
        if node is not None:
            self.inspector.show_node(
                self.graph, node, active_scope=self.scene.active_scope)

    def _create_compound_from_selection(self, member_names):
        if not member_names or self.scene.active_scope is not None:
            return
        default_name = "NG_%s" % member_names[0]
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Create compound graph",
            "Nodegraph name:",
            QtWidgets.QLineEdit.Normal, default_name)
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        xs = [self.graph.node(n).position[0] for n in member_names]
        ys = [self.graph.node(n).position[1] for n in member_names]
        position = (sum(xs) / len(xs), sum(ys) / len(ys))
        try:
            self.scene.stack.push(commands.CreateCompoundCommand(
                self.graph, name, member_names, position))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "VredX", str(exc))
            return
        self._dirty = True

    def _add_graph_output_for_node(self, node_name):
        scope = self.scene.active_scope
        if not scope:
            return
        node = self.graph.nodes.get(node_name)
        if node is None or node.compound != scope or node.is_compound:
            return
        outputs = list(node.nodedef.outputs)
        if not outputs:
            QtWidgets.QMessageBox.information(
                self, "VredX", "This node has no output ports to export.")
            return
        default_name = self.graph.unique_compound_output_name(
            scope, "%s_output" % node.name)
        if len(outputs) == 1:
            port = outputs[0].name
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Add graph output",
                "Output name on the compound node:",
                QtWidgets.QLineEdit.Normal, default_name)
            if not ok or not name.strip():
                return
            output_name = name.strip()
        else:
            items = ["%s (%s)" % (o.name, o.type) for o in outputs]
            port_item, ok = QtWidgets.QInputDialog.getItem(
                self, "Add graph output", "Port:", items, 0, False)
            if not ok:
                return
            port = outputs[items.index(port_item)].name
            name, ok = QtWidgets.QInputDialog.getText(
                self, "Add graph output",
                "Output name on the compound node:",
                QtWidgets.QLineEdit.Normal, default_name)
            if not ok or not name.strip():
                return
            output_name = name.strip()
        try:
            self.scene.stack.push(commands.AddCompoundOutputCommand(
                self.graph, scope, output_name, node_name, port))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "VredX", str(exc))
            return
        self._dirty = True
        self.tabs.setCurrentWidget(self.inspector)
        self._select_node(node_name)
        self.inspector.show_node(
            self.graph, node, active_scope=self.scene.active_scope)

    def _dissolve_compound(self, compound_name):
        if compound_name not in self.graph.compounds:
            return
        if (self.scene.active_scope == compound_name
                or compound_name in self._nav_stack):
            self._navigate_to_scope(None)
        try:
            self.scene.stack.push(commands.DissolveCompoundCommand(
                self.graph, compound_name))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "VredX", str(exc))
            return
        self._dirty = True
        self._inspector_selection = []
        self.scene.clearSelection()
        self.inspector.show_selection(
            self.graph, [], active_scope=self.scene.active_scope)
        self.view.fit_all()

    def _select_node(self, node_name):
        self.scene.clearSelection()
        item = self.scene.node_items.get(node_name)
        if item is not None:
            item.setSelected(True)
            self.view.centerOn(item)

    def _add_from_palette(self, nodedef_name):
        nodedef = self.library.get(nodedef_name)
        if nodedef is not None:
            center = self.view.mapToScene(
                self.view.viewport().rect().center())
            self.scene.add_node_at(nodedef, center)

    def _undo(self):
        self.ensure_editor_ready()
        self.scene.stack.undo()

    def _redo(self):
        self.ensure_editor_ready()
        self.scene.stack.redo()

    def _delete_selected(self):
        self.ensure_editor_ready()
        self.scene.delete_selected()

    def _duplicate_selected(self):
        self.ensure_editor_ready()
        self.scene.duplicate_selected()

    def _quick_add_node(self):
        self.ensure_editor_ready()
        self.view.show_quick_add()

    def _fit_view(self):
        self.ensure_editor_ready()
        self.view.fit_all()

    def _toggle_palette(self, visible):
        self.palette_panel.setVisible(visible)

    def _toggle_preview(self, visible):
        self.preview_panel.setVisible(visible)

    def _toggle_attributes(self, visible):
        self.tabs.setVisible(visible)

    def _toggle_baking(self, visible):
        if self._baking_tab_index is None:
            return
        if visible:
            if self._menu_attributes is not None:
                self._menu_attributes.setChecked(True)
            self.tabs.setCurrentIndex(self._baking_tab_index)
            self.baking_panel.sync_from_graph()
        elif self.tabs.currentIndex() == self._baking_tab_index:
            self.tabs.setCurrentIndex(0)

    def _on_attributes_tab_changed(self, index):
        if self._menu_baking is None or self._baking_tab_index is None:
            return
        on_baking = index == self._baking_tab_index
        if self._menu_baking.isChecked() != on_baking:
            self._menu_baking.blockSignals(True)
            self._menu_baking.setChecked(on_baking)
            self._menu_baking.blockSignals(False)

    def show_baking_panel(self):
        """Show the baking panel (VREDX menu shortcut)."""
        if self._baking_tab_index is None:
            return
        if self._menu_baking is not None:
            self._menu_baking.setChecked(True)
        else:
            self._toggle_baking(True)

    def _pop_out_editor(self):
        if self._floating_shell is not None:
            self._floating_shell.showNormal()
            self._floating_shell.raise_()
            self._floating_shell.activateWindow()
            return
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            self._docked_parent = parent
            self._docked_layout = parent.layout()
            self._docked_layout.removeWidget(self)
        self._floating_shell = VredXFloatingShell(self)
        self._floating_shell.show()
        self._menu_pop_out.setEnabled(False)
        self._menu_dock.setEnabled(True)

    def _dock_editor(self):
        if self._floating_shell is None:
            return
        self._floating_shell.hide()
        if self._docked_parent is not None and self._docked_layout is not None:
            self.setParent(self._docked_parent)
            self._docked_layout.addWidget(self)
            self.show()
        self._floating_shell.setCentralWidget(None)
        self._floating_shell.deleteLater()
        self._floating_shell = None
        self._menu_pop_out.setEnabled(True)
        self._menu_dock.setEnabled(False)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_S and \
                event.modifiers() & QtCore.Qt.ControlModifier:
            self.save()
            event.accept()
            return
        super().keyPressEvent(event)

    def shutdown(self):
        """Called by the plugin before unload."""
        self._cleanup_import_temp()
        self._validate_timer.stop()
        self._apply_timer.stop()
        self._preview_timer.stop()
        self._preview_pull_timer.stop()
        if vred_api.INSIDE_VRED:
            try:
                vred_api.vrMaterialService.previewsChanged.disconnect(
                    self._on_previews_changed)
            except (AttributeError, RuntimeError, TypeError):
                pass


class SceneMaterialsPanel(QtWidgets.QWidget):
    """MaterialX materials in the current VRED scene."""

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._window = parent

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.list = QtWidgets.QListWidget(self)
        layout.addWidget(self.list, 1)

        row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton("Refresh", self)
        refresh.clicked.connect(self.refresh)
        self.open_button = QtWidgets.QPushButton("Open in editor", self)
        self.open_button.clicked.connect(self._open_selected)
        row.addWidget(refresh)
        row.addWidget(self.open_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.info = QtWidgets.QLabel(self)
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: #9a9a9f;")
        layout.addWidget(self.info)

        if not vred_api.INSIDE_VRED:
            self.info.setText("Scene materials are available inside "
                              "VRED only.")
            self.open_button.setEnabled(False)
        else:
            self.refresh()

    def refresh(self):
        if not vred_api.INSIDE_VRED:
            return
        self.list.clear()
        try:
            materials = self._bridge.scene_materialx_materials()
        except Exception as exc:
            self.info.setText(str(exc))
            return
        for material in materials:
            item = QtWidgets.QListWidgetItem(material.getName())
            item.setData(QtCore.Qt.UserRole,
                         self._bridge.material_source_path(material))
            self.list.addItem(item)
        self.info.setText("%d MaterialX material(s) in scene."
                          % self.list.count())

    def _open_selected(self):
        item = self.list.currentItem()
        if item is None:
            return
        path = item.data(QtCore.Qt.UserRole)
        if not path or not os.path.isfile(path):
            self.info.setText(
                "No source .mtlx on disk for '%s'. Its document was "
                "embedded in the project; edit its attributes in VRED's "
                "material editor instead." % item.text())
            return
        window = self._window
        while window is not None and not isinstance(window, VredXWindow):
            window = window.parentWidget()
        if window is not None:
            window.open_document(path)
