# -*- coding: utf-8 -*-
#
# Licensed under the terms of the BSD 3-Clause or the CeCILL-B License
# (see codraft/__init__.py for details)

"""
CodraFT Panel widgets (core.gui.panel)

Signal and Image Panel widgets relie on components:

  * `ObjectProp`: widget handling signal/image properties
  using a guidata DataSet

  * `core.gui.panel.objectlist.ObjectList`: widget handling signal/image list

  * `core.gui.panel.actionhandler.SignalActionHandler` or `ImageActionHandler`:
  classes handling Qt actions

  * `core.gui.panel.plotitemlist.SignalItemList` or `ImageItemList`:
  classes handling guiqwt plot items

  * `core.gui.panel.processor.signal.SignalProcessor` or
  `core.gui.panel.processor.image.ImageProcessor`: classes handling computing features

  * `core.gui.panel.roieditor.SignalROIEditor` or `ImageROIEditor`:
  classes handling ROI editor widgets
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...

import abc
import os.path as osp
import re
import traceback
from typing import List

import guidata.dataset.qtwidgets as gdq
import numpy as np
from guidata.configtools import get_icon
from guidata.qthelpers import add_actions
from guidata.utils import update_dataset
from guiqwt.io import imread, imwrite, iohandler
from guiqwt.plot import CurveDialog, ImageDialog
from guiqwt.tools import (
    AnnotatedCircleTool,
    AnnotatedEllipseTool,
    AnnotatedPointTool,
    AnnotatedRectangleTool,
    AnnotatedSegmentTool,
    FreeFormTool,
    HCursorTool,
    LabelTool,
    VCursorTool,
    XCursorTool,
)
from qtpy import QtCore as QC
from qtpy import QtWidgets as QW
from qtpy.compat import getopenfilename, getopenfilenames, getsavefilename

from codraft.config import APP_NAME, Conf, _
from codraft.core.gui import actionhandler, objectlist, plotitemlist, roieditor
from codraft.core.gui.processor.image import ImageProcessor
from codraft.core.gui.processor.signal import SignalProcessor
from codraft.core.model.base import MetadataItem, ResultShape
from codraft.core.model.image import (
    ImageDatatypes,
    ImageParam,
    create_image,
    create_image_from_param,
    new_image_param,
)
from codraft.core.model.signal import (
    SignalParam,
    create_signal,
    create_signal_from_param,
    new_signal_param,
)
from codraft.utils.qthelpers import (
    exec_dialog,
    qt_try_loadsave_file,
    save_restore_stds,
)

#  Registering MetadataItem edit widget
gdq.DataSetEditLayout.register(MetadataItem, gdq.ButtonWidget)


class ObjectProp(QW.QWidget):
    """Object handling panel properties"""

    def __init__(self, panel, paramclass):
        super().__init__(panel)
        self.properties = gdq.DataSetEditGroupBox(_("Properties"), paramclass)
        self.properties.SIG_APPLY_BUTTON_CLICKED.connect(panel.properties_changed)
        self.properties.setEnabled(False)
        self.add_prop_layout = QW.QHBoxLayout()
        playout = self.properties.edit.layout
        playout.addLayout(
            self.add_prop_layout, playout.rowCount() - 1, 0, 1, 1, QC.Qt.AlignLeft
        )
        hlayout = QW.QHBoxLayout()
        hlayout.addWidget(self.properties)
        vlayout = QW.QVBoxLayout()
        vlayout.addLayout(hlayout)
        vlayout.addStretch()
        self.setLayout(vlayout)

    def add_button(self, button):
        """Add additional button on bottom of properties panel"""
        self.add_prop_layout.addWidget(button)


class BasePanelMeta(type(QW.QSplitter), abc.ABCMeta):
    """Mixed metaclass to avoid conflicts"""


class BasePanel(QW.QSplitter, metaclass=BasePanelMeta):
    """Object handling the item list, the selected item properties and plot"""

    PANEL_STR = ""  # e.g. "Signal Panel"
    PARAMCLASS = SignalParam  # Replaced by the right class in child object
    DIALOGCLASS = CurveDialog  # Idem
    ANNOTATION_TOOLS = (LabelTool, VCursorTool, HCursorTool, XCursorTool)
    DIALOGSIZE = (800, 600)
    PREFIX = ""  # e.g. "s"
    OPEN_FILTERS = ""  # Qt file open dialog filters
    H5_PREFIX = ""
    SIG_STATUS_MESSAGE = QC.Signal(str)  # emitted by "qt_try_except" decorator
    SIG_OBJECT_ADDED = QC.Signal()
    SIG_OBJECT_REMOVED = QC.Signal()
    SIG_REFRESH_PLOT = QC.Signal()
    ROIDIALOGOPTIONS = {}
    ROIDIALOGCLASS = roieditor.BaseROIEditor  # Replaced in child object

    @abc.abstractmethod
    def __init__(self, parent, plotwidget, toolbar):
        super().__init__(QC.Qt.Vertical, parent)
        self.setObjectName(self.PREFIX)
        self.mainwindow = parent
        self.objprop = ObjectProp(self, self.PARAMCLASS)
        self.objlist = objectlist.ObjectList(self)
        self.itmlist = None
        self.processor = None
        self.acthandler = None
        self.__metadata_clipboard = {}
        self.context_menu = QW.QMenu()

    def setup_panel(self):
        """Setup panel"""
        self.processor.SIG_ADD_SHAPE.connect(self.itmlist.add_shapes)
        self.SIG_REFRESH_PLOT.connect(self.itmlist.refresh_plot)
        self.objlist.itemSelectionChanged.connect(self.selection_changed)
        self.objlist.currentRowChanged.connect(self.current_item_changed)
        self.objlist.SIG_ITEM_DOUBLECLICKED.connect(
            lambda row: self.open_separate_view([row])
        )
        self.objlist.SIG_CONTEXT_MENU.connect(self.__popup_contextmenu)
        self.objprop.properties.SIG_APPLY_BUTTON_CLICKED.connect(
            self.properties_changed
        )
        self.addWidget(self.objlist)
        self.addWidget(self.objprop)

    def get_category_actions(self, category):
        """Return actions for category"""
        return self.acthandler.feature_actions[category]

    def __popup_contextmenu(self, position: QC.QPoint):
        """Popup context menu at position"""
        # Note: For now, this is completely unnecessary to clear context menu everytime,
        # but implementing it this way could be useful in the future in menu contents
        # should take into account current object selection
        self.context_menu.clear()
        add_actions(self.context_menu, self.acthandler.actlist_cmenu)
        self.context_menu.popup(position)

    # ------Creating, adding, removing objects------------------------------------------
    def create_object(self, title=None):
        """Create object (signal or image)

        :param str title: Title of the object
        """
        # TODO: [P2] Add default signal/image visualization settings
        # 1. Initialize here (at object creation) metadata with default settings
        #    (see guiqwt.styles.CurveParam and ImageParam for inspiration)
        # 2. Add a dialog box to edit default settings in main window
        #    (use a guidata dataset with only a selection of items from guiqwt.styles
        #     classes)
        # 3. Update all active objects when settings were changed
        # 4. Persist settings in .INI configuration file
        obj = self.PARAMCLASS(title=title)
        obj.title = title
        return obj

    def add_object(self, obj, refresh=True):
        """Add signal/image object"""
        self.objlist.append(obj)
        row = len(self.objlist) - 1
        item = self.itmlist.add_item_to_plot(row)
        if refresh:
            self.objlist.refresh_list(-1)
        self.SIG_OBJECT_ADDED.emit()
        return item

    # TODO: [P2] New feature: move objects up/down
    def insert_object(self, obj, row, refresh=True):
        """Insert signal/image object after row"""
        self.objlist.insert(row, obj)
        self.itmlist.insert(row)
        if refresh:
            self.objlist.refresh_list(new_current_row=row + 1)
        self.SIG_OBJECT_ADDED.emit()

    def duplicate_object(self):
        """Duplication signal/image object"""
        if not self.mainwindow.confirm_memory_state():
            return
        rows = sorted(self.objlist.get_selected_rows(), reverse=True)
        row = None
        for row in rows:
            obj = self.objlist[row]
            objcopy = self.create_object()
            objcopy.title = obj.title
            objcopy.copy_data_from(obj)
            self.insert_object(objcopy, row=row + 1, refresh=False)
        self.objlist.refresh_list(new_current_row=row + 1)
        self.SIG_REFRESH_PLOT.emit()

    def copy_metadata(self):
        """Copy object metadata"""
        row = self.objlist.get_selected_rows()[0]
        obj = self.objlist[row]
        self.__metadata_clipboard = obj.metadata.copy()
        pfx = self.objlist.prefix
        new_pref = f"{pfx}{row:03d}_"
        for key, value in obj.metadata.items():
            if ResultShape.match(key, value):
                mshape = ResultShape.from_metadata_entry(key, value)
                if not re.match(pfx + r"[0-9]{3}[\s]*", mshape.label):
                    # Handling additional result (e.g. diameter)
                    for a_key, a_value in obj.metadata.items():
                        if isinstance(a_key, str) and a_key.startswith(mshape.label):
                            self.__metadata_clipboard.pop(a_key)
                            self.__metadata_clipboard[new_pref + a_key] = a_value
                    mshape.label = new_pref + mshape.label
                    # Handling result shape
                    self.__metadata_clipboard.pop(key)
                    self.__metadata_clipboard[mshape.key] = value

    def paste_metadata(self):
        """Paste metadata to selected object(s)"""
        rows = sorted(self.objlist.get_selected_rows(), reverse=True)
        row = None
        for row in rows:
            obj = self.objlist[row]
            obj.metadata.update(self.__metadata_clipboard)
        self.SIG_REFRESH_PLOT.emit()

    def remove_object(self):
        """Remove signal/image object"""
        rows = sorted(self.objlist.get_selected_rows(), reverse=True)
        for row in rows:
            del self.objlist[row]
            del self.itmlist[row]
        self.objlist.refresh_list(0)
        self.SIG_REFRESH_PLOT.emit()
        self.SIG_OBJECT_REMOVED.emit()

    def delete_all_objects(self):
        """Confirm before removing all objects"""
        if len(self.objlist) == 0:
            return
        answer = QW.QMessageBox.warning(
            self,
            _("Delete all"),
            _("Do you want to delete all objects from the %s?") % self.PANEL_STR,
            QW.QMessageBox.Yes | QW.QMessageBox.No,
        )
        if answer == QW.QMessageBox.Yes:
            self.remove_all_objects()

    def remove_all_objects(self):
        """Remove all signal/image objects"""
        self.objlist.remove_all()
        self.itmlist.remove_all()
        self.objlist.refresh_list(0)
        self.SIG_REFRESH_PLOT.emit()
        self.SIG_OBJECT_REMOVED.emit()

    def delete_metadata(self):
        """Delete object metadata"""
        for index, row in enumerate(self.objlist.get_selected_rows()):
            self.objlist[row].metadata = {}
            if index == 0:
                self.current_item_changed(row)
        self.SIG_REFRESH_PLOT.emit()

    @abc.abstractmethod
    def new_object(self, newparam=None, addparam=None, edit=True):
        """Create a new object (signal/image).

        :param guidata.dataset.DataSet newparam: new object parameters
        :param guidata.dataset.datatypes.DataSet addparam: additional parameters
        :param bool edit: Open a dialog box to edit parameters (default: True)
        """

    def open_objects(self, filenames: List[str] = None) -> None:
        """Open objects from file (signals/images)"""
        if not self.mainwindow.confirm_memory_state():
            return
        if filenames is None:
            basedir = Conf.main.base_dir.get()
            with save_restore_stds():
                filenames, _filter = getopenfilenames(
                    self, _("Open"), basedir, self.OPEN_FILTERS
                )
        for filename in filenames:
            Conf.main.base_dir.set(filename)
            with qt_try_loadsave_file(self.parent(), filename, "load"):
                self.open_object(filename)

    def save_objects(self, filenames: List[str] = None) -> None:
        """Save selected objects to file (signal/image)"""
        rows = self.objlist.get_selected_rows()
        if filenames is None:
            filenames = [None] * len(rows)
        assert len(filenames) == len(rows)
        for index, row in enumerate(rows):
            filename = filenames[index]
            obj = self.objlist[row]
            self.save_object(obj, filename)

    @abc.abstractmethod
    def save_object(self, obj, filename: str = None) -> None:
        """Save object to file (signal/image)"""

    def import_metadata_from_file(self, filename: str = None):
        """Import metadata from file (JSON)"""
        if filename is None:
            basedir = Conf.main.base_dir.get()
            with save_restore_stds():
                filename, _filter = getopenfilename(
                    self, _("Import metadata"), basedir, "*.json"
                )
        if filename:
            Conf.main.base_dir.set(filename)
            row = self.objlist.get_selected_rows()[0]
            obj = self.objlist[row]
            with qt_try_loadsave_file(self.parent(), filename, "load"):
                obj.import_metadata_from_file(filename)
            self.SIG_REFRESH_PLOT.emit()

    def export_metadata_from_file(self, filename: str = None):
        """Export metadata to file (JSON)"""
        row = self.objlist.get_selected_rows()[0]
        obj = self.objlist[row]
        if filename is None:
            basedir = Conf.main.base_dir.get()
            with save_restore_stds():
                filename, _filt = getsavefilename(
                    self, _("Export metadata"), basedir, "*.json"
                )
        if filename:
            Conf.main.base_dir.set(filename)
            with qt_try_loadsave_file(self.parent(), filename, "save"):
                obj.export_metadata_to_file(filename)

    # ------Serializing/deserializing objects-------------------------------------------
    def serialize_to_hdf5(self, writer):
        """Serialize objects to a HDF5 file"""
        with writer.group(self.H5_PREFIX):
            for idx, obj in enumerate(self.objlist):
                title = re.sub("[^-a-zA-Z0-9_.() ]+", "", obj.title.replace("/", "_"))
                name = f"{self.PREFIX}{idx:03d}: {title}"
                with writer.group(name):
                    obj.serialize(writer)

    def deserialize_from_hdf5(self, reader):
        """Deserialize objects from a HDF5 file"""
        with reader.group(self.H5_PREFIX):
            for name in reader.h5.get(self.H5_PREFIX, []):
                obj = self.PARAMCLASS()
                with reader.group(name):
                    obj.deserialize(reader)
                    self.add_object(obj)
                    QW.QApplication.processEvents()

    # ------Refreshing GUI--------------------------------------------------------------
    def current_item_changed(self, row):
        """Current item changed"""
        if row != -1:
            update_dataset(self.objprop.properties.dataset, self.objlist[row])
            self.objprop.properties.get()

    def selection_changed(self):
        """Signal list: selection changed"""
        row = self.objlist.currentRow()
        self.objprop.properties.setDisabled(row == -1)
        self.SIG_REFRESH_PLOT.emit()
        self.acthandler.selection_rows_changed()

    def properties_changed(self):
        """The properties 'Apply' button was clicked: updating signal"""
        row = self.objlist.currentRow()
        update_dataset(self.objlist[row], self.objprop.properties.dataset)
        self.objlist.refresh_list()
        self.SIG_REFRESH_PLOT.emit()

    # ------Plotting data in modal dialogs----------------------------------------------
    def open_separate_view(self, rows=None):
        """
        Open separate view for visualizing selected objects

        :param list rows: List of row indexes for the objects to be shown in dialog
        """
        title = _("Annotations")
        rows = self.objlist.get_selected_rows()
        row = rows[0]
        obj = self.objlist[row]
        dlg = self.create_new_dialog(rows, edit=True, name="new_window")
        width, height = self.DIALOGSIZE
        dlg.resize(width, height)
        dlg.plot_widget.itemlist.setVisible(True)
        toolbar = QW.QToolBar(title, self)
        dlg.button_layout.insertWidget(0, toolbar)
        # dlg.layout().insertWidget(1, toolbar)  # other possible location
        # dlg.plot_layout.addWidget(toolbar, 1, 0, 1, 1)  # other possible location
        dlg.add_toolbar(toolbar, id(toolbar))
        toolbar.setToolButtonStyle(QC.Qt.ToolButtonTextUnderIcon)
        for tool in self.ANNOTATION_TOOLS:
            dlg.add_tool(tool, toolbar_id=id(toolbar))
        plot = dlg.get_plot()
        plot.unselect_all()
        for item in plot.items:
            item.set_selectable(False)
        for item in obj.iterate_shape_items(editable=True):
            plot.add_item(item)
        if exec_dialog(dlg):
            items = plot.get_items()
            rw_items = [item for item in items if not item.is_readonly()]
            if rw_items:
                obj.set_annotations_from_items(rw_items)
            self.current_item_changed(row)
            self.SIG_REFRESH_PLOT.emit()

    def toggle_show_titles(self, state):
        """Toggle show annotations option"""
        Conf.view.show_label.set(state)
        for obj in self.objlist:
            obj.metadata[obj.METADATA_LBL] = state
        self.SIG_REFRESH_PLOT.emit()

    def create_new_dialog(
        self,
        rows,
        edit=False,
        toolbar=True,
        title=None,
        tools=None,
        name=None,
        options=None,
    ):
        """
        Create new pop-up signal/image plot dialog

        :param list rows: List of row indexes for the objects to be shown in dialog
        :param bool edit: If True, show "OK" and "Cancel" buttons
        :param bool toolbar: If True, add toolbar
        :param str title: Title of the dialog box
        :param list tools: List of plot tools
        :param str name: Name of the widget (used as screenshot basename)
        :param dict options: Plot options
        """
        if title is not None or len(rows) == 1:
            if title is None:
                title = self.objlist.get_sel_object().title
            title = f"{title} - {APP_NAME}"
        else:
            title = APP_NAME
        plot_options = self.itmlist.get_current_plot_options()
        if options is not None:
            plot_options.update(options)
        dlg = self.DIALOGCLASS(
            parent=self,
            wintitle=title,
            edit=edit,
            options=plot_options,
            toolbar=toolbar,
        )
        dlg.setWindowIcon(get_icon("codraft.svg"))
        dlg.setObjectName(f"{self.PREFIX}_{name}")
        if tools is not None:
            for tool in tools:
                dlg.add_tool(tool)
        plot = dlg.get_plot()
        for row in rows:
            item = self.itmlist.make_item_from_existing(row)
            item.set_readonly(True)
            plot.add_item(item, z=0)
        plot.set_active_item(item)
        plot.replot()
        return dlg

    def create_new_dialog_for_selection(
        self, title, name, options=None, toolbar=False, tools=None
    ):
        """
        Create new pop-up dialog for the currently selected signal/image

        :param str title: Title of the dialog box
        :param str name: Name of the widget (used as screenshot basename)
        :param dict options: Plot options
        :param list tools: List of plot tools
        :return: tuple (dialog, current_object)
        """
        row = self.objlist.get_selected_rows()[0]
        obj = self.objlist[row]
        dlg = self.create_new_dialog(
            [row],
            edit=True,
            toolbar=toolbar,
            title=f"{title} - {obj.title}",
            tools=tools,
            name=name,
            options=options,
        )
        return dlg, obj

    def get_roi_dialog(self) -> np.ndarray:
        """Get ROI data (array) from specific dialog box"""
        roi_s = _("Regions of interest")
        dlg, obj = self.create_new_dialog_for_selection(
            roi_s, "roi_dialog", self.ROIDIALOGOPTIONS
        )
        fmt = obj.metadata.get(obj.METADATA_FMT, "%s")
        roi_items = list(obj.iterate_roi_items(fmt, True))
        plot = dlg.get_plot()
        plot.unselect_all()
        for item in plot.items:
            item.set_selectable(False)
        roi_editor = self.ROIDIALOGCLASS(
            dlg, roi_items, lambda: obj.new_roi_item(fmt, True, editable=True)
        )
        dlg.plot_layout.addWidget(roi_editor, 1, 0, 1, 1)
        if exec_dialog(dlg):
            coords = roi_editor.get_roi_coords()
            return obj.roi_coords_to_indexes(coords)
        return None

    def get_object_dialog(
        self, parent: QW.QWidget, title: str
    ) -> objectlist.GetObjectDialog:
        """Get object dialog"""
        dlg = objectlist.GetObjectDialog(parent, self, title)
        if exec_dialog(dlg):
            return dlg.get_object()
        return None


class SignalPanel(BasePanel):
    """Object handling the item list, the selected item properties and plot,
    specialized for Signal objects"""

    PANEL_STR = "Signal Panel"
    PARAMCLASS = SignalParam
    DIALOGCLASS = CurveDialog
    PREFIX = "s"
    OPEN_FILTERS = f'{_("Text files")} (*.txt *.csv)\n{_("NumPy arrays")} (*.npy)'
    H5_PREFIX = "CodraFT_Sig"
    ROIDIALOGCLASS = roieditor.SignalROIEditor

    # pylint: disable=duplicate-code

    def __init__(self, parent, plotwidget, toolbar):
        super().__init__(parent, plotwidget, toolbar)
        self.itmlist = plotitemlist.SignalItemList(self, self.objlist, plotwidget)
        self.processor = SignalProcessor(self, self.objlist)
        self.acthandler = actionhandler.SignalActionHandler(
            self, self.objlist, self.itmlist, self.processor, toolbar
        )
        self.setup_panel()

    # ------Creating, adding, removing objects------------------------------------------
    def new_object(self, newparam=None, addparam=None, edit=True):
        """Create a new signal.

        :param codraft.core.model.signal.SignalNewParam newparam: new signal parameters
        :param guidata.dataset.datatypes.DataSet addparam: additional parameters
        :param bool edit: Open a dialog box to edit parameters (default: True)
        """
        if not self.mainwindow.confirm_memory_state():
            return
        curobj = self.objlist.get_sel_object(-1)
        if curobj is not None:
            newparam = newparam if newparam is not None else new_signal_param()
            newparam.size = len(curobj.data)
            newparam.xmin = curobj.x.min()
            newparam.xmax = curobj.x.max()
        signal = create_signal_from_param(
            newparam, addparam=addparam, edit=edit, parent=self
        )
        if signal is not None:
            self.add_object(signal)

    def open_object(self, filename: str) -> None:
        """Open object from file (signal/image)"""
        if osp.splitext(filename)[1] == ".npy":
            xydata = np.load(filename)
        else:
            for delimiter in ("\t", ",", " ", ";"):
                try:
                    xydata = np.loadtxt(filename, delimiter=delimiter)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError
        assert len(xydata.shape) in (1, 2), "Data not supported"
        signal = create_signal(osp.basename(filename))
        if len(xydata.shape) == 1:
            signal.set_xydata(np.arange(xydata.size), xydata)
        else:
            rows, cols = xydata.shape
            for colnb in (2, 3, 4):
                if cols == colnb and rows > colnb:
                    xydata = xydata.T
                    break
            if cols == 3:
                # x, y, dy
                xarr, yarr, dyarr = xydata
                signal.set_xydata(xarr, yarr, dx=None, dy=dyarr)
            else:
                signal.xydata = xydata
        self.add_object(signal)

    def save_object(self, obj, filename: str = None) -> None:
        """Save object to file (signal/image)"""
        if filename is None:
            basedir = Conf.main.base_dir.get()
            with save_restore_stds():
                filename, _filter = getsavefilename(  # pylint: disable=duplicate-code
                    self, _("Save as"), basedir, _("CSV files") + " (*.csv)"
                )
        if filename:
            Conf.main.base_dir.set(filename)
            try:
                np.savetxt(filename, obj.xydata, delimiter=",")
            except Exception as msg:  # pylint: disable=broad-except
                traceback.print_exc()
                QW.QMessageBox.critical(
                    self.parent(),
                    APP_NAME,
                    (_("%s could not be written:") % osp.basename(filename))
                    + "\n"
                    + str(msg),
                )


class ImagePanel(BasePanel):
    """Object handling the item list, the selected item properties and plot,
    specialized for Image objects"""

    PANEL_STR = "Image Panel"
    PARAMCLASS = ImageParam
    DIALOGCLASS = ImageDialog
    DIALOGSIZE = (800, 800)
    ANNOTATION_TOOLS = (
        AnnotatedCircleTool,
        AnnotatedSegmentTool,
        AnnotatedRectangleTool,
        AnnotatedPointTool,
        AnnotatedEllipseTool,
        LabelTool,
        FreeFormTool,
    )
    PREFIX = "i"
    OPEN_FILTERS = iohandler.get_filters("load", dtype=None)
    H5_PREFIX = "CodraFT_Ima"
    ROIDIALOGOPTIONS = dict(show_itemlist=True, show_contrast=False)
    ROIDIALOGCLASS = roieditor.ImageROIEditor

    # pylint: disable=duplicate-code

    def __init__(self, parent, plotwidget, toolbar):
        super().__init__(parent, plotwidget, toolbar)
        self.itmlist = plotitemlist.ImageItemList(self, self.objlist, plotwidget)
        self.processor = ImageProcessor(self, self.objlist)
        self.acthandler = actionhandler.ImageActionHandler(
            self, self.objlist, self.itmlist, self.processor, toolbar
        )
        self.setup_panel()

    # ------Creating, adding, removing objects------------------------------------------
    def new_object(self, newparam=None, addparam=None, edit=True):
        """Create a new image.

        :param codraft.core.model.image.ImageNewParam newparam: new image parameters
        :param guidata.dataset.datatypes.DataSet addparam: additional parameters
        :param bool edit: Open a dialog box to edit parameters (default: True)
        """
        if not self.mainwindow.confirm_memory_state():
            return
        curobj = self.objlist.get_sel_object(-1)
        if curobj is not None:
            newparam = newparam if newparam is not None else new_image_param()
            newparam.width, newparam.height = curobj.size
            newparam.dtype = ImageDatatypes.from_dtype(curobj.data.dtype)
        image = create_image_from_param(
            newparam, addparam=addparam, edit=edit, parent=self
        )
        if image is not None:
            self.add_object(image)

    def open_object(self, filename: str) -> None:
        """Open object from file (signal/image)"""
        data = imread(filename, to_grayscale=False)
        if filename.lower().endswith(".sif") and len(data.shape) == 3:
            for idx in range(data.shape[0]):
                image = create_image(
                    osp.basename(filename) + "_Im" + str(idx), data[idx, ::]
                )
                self.add_object(image)
        else:
            if data.ndim == 3:
                # Converting to grayscale
                data = data[..., :4].mean(axis=2)
            image = create_image(osp.basename(filename), data)
            if osp.splitext(filename)[1].lower() == ".dcm":
                from pydicom import dicomio  # pylint: disable=C0415,E0401

                image.dicom_template = dicomio.read_file(
                    filename, stop_before_pixels=True, force=True
                )
            self.add_object(image)

    def save_object(self, obj, filename: str = None) -> None:
        """Save object to file (signal/image)"""
        if filename is None:
            basedir = Conf.main.base_dir.get()
            with save_restore_stds():
                filename, _filter = getsavefilename(  # pylint: disable=duplicate-code
                    self,
                    _("Save as"),
                    basedir,
                    iohandler.get_filters(
                        "save", dtype=obj.data.dtype, template=obj.dicom_template
                    ),
                )
        if filename:
            Conf.main.base_dir.set(filename)
            kwargs = {}
            if osp.splitext(filename)[1].lower() == ".dcm":
                kwargs["template"] = obj.dicom_template
            with qt_try_loadsave_file(self.parent(), filename, "save"):
                imwrite(filename, obj.data, **kwargs)