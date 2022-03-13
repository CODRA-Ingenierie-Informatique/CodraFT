# -*- coding: utf-8 -*-
#
# Licensed under the terms of the CECILL License
# (see codraft/__init__.py for details)

"""
CodraFT Datasets
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...

import abc
import re
import numpy as np

import guidata.dataset.datatypes as gdt
import guidata.dataset.dataitems as gdi

from codraft.config import _

ROI_KEY = "_ROI"

CI_RECTANGLE, CI_CIRCLE, CI_ELLIPSE, CI_SEGMENT, CI_MARKER = range(5)


# === Object (signal/image) interface ------------------------------------------
class ObjectItfMeta(abc.ABCMeta, gdt.DataSetMeta):
    """Mixed metaclass to avoid conflicts"""


class ObjectItf(metaclass=ObjectItfMeta):
    """Object (signal/image) interface"""

    @property
    @abc.abstractmethod
    def data(self):
        """Data"""

    @abc.abstractmethod
    def copy_data_from(self, other, dtype=None):
        """Copy data from other dataset instance"""

    @abc.abstractmethod
    def set_data_type(self, dtype):
        """Change data type"""

    @abc.abstractmethod
    def get_roi_param(self, *defaults):
        """Return ROI parameters dataset"""

    @abc.abstractmethod
    def get_roi(self):
        """Return signal ROI"""

    @abc.abstractmethod
    def set_roi(self, roiparam):
        """Set signal ROI"""


# === Core classes -------------------------------------------------------------
class SignalParam(gdt.DataSet, ObjectItf):
    """Signal dataset"""

    _tabs = gdt.BeginTabGroup("all")

    _datag = gdt.BeginGroup(_("Data and metadata"))
    title = gdi.StringItem(_("Signal title"), default=_("Untitled"))
    xydata = gdi.FloatArrayItem(_("Data"), transpose=True, minmax="rows")
    metadata = gdi.DictItem(_("Metadata"), default={})
    _e_datag = gdt.EndGroup(_("Data and metadata"))

    _unitsg = gdt.BeginGroup(_("Titles and units"))
    title = gdi.StringItem(_("Signal title"), default=_("Untitled"))
    _tabs_u = gdt.BeginTabGroup("units")
    _unitsx = gdt.BeginGroup(_("X-axis"))
    xlabel = gdi.StringItem(_("Title"))
    xunit = gdi.StringItem(_("Unit"))
    _e_unitsx = gdt.EndGroup(_("X-axis"))
    _unitsy = gdt.BeginGroup(_("Y-axis"))
    ylabel = gdi.StringItem(_("Title"))
    yunit = gdi.StringItem(_("Unit"))
    _e_unitsy = gdt.EndGroup(_("Y-axis"))
    _e_tabs_u = gdt.EndTabGroup("units")
    _e_unitsg = gdt.EndGroup(_("Titles and units"))

    _e_tabs = gdt.EndTabGroup("all")

    def copy_data_from(self, other, dtype=None):
        """Copy data from other dataset instance"""
        if dtype not in (None, float):
            raise RuntimeError("Signal data only supports float64 dtype")
        self.metadata = other.metadata.copy()
        self.xydata = np.array(other.xydata, copy=True, dtype=dtype)

    def set_data_type(self, dtype):  # pylint: disable=unused-argument,no-self-use
        """Change data type"""
        raise RuntimeError("Setting data type is not support for signals")

    def set_xydata(self, x, y, dx=None, dy=None):
        """Set xy data"""
        if x is not None:
            x = np.array(x, dtype=float)
        if y is not None:
            y = np.array(y, dtype=float)
        if dx is not None:
            dx = np.array(dx, dtype=float)
        if dy is not None:
            dy = np.array(dy, dtype=float)
        if dx is None and dy is None:
            self.xydata = np.vstack([x, y])
        else:
            if dx is None:
                dx = np.zeros_like(dy)
            else:
                dy = np.zeros_like(dx)
            self.xydata = np.vstack((x, y, dx, dy))

    def get_x(self):
        """Get x data"""
        if self.xydata is not None:
            return self.xydata[0]
        return None

    def set_x(self, data):
        """Set x data"""
        self.xydata[0] = np.array(data, dtype=float)

    def get_y(self):
        """Get y data"""
        if self.xydata is not None:
            return self.xydata[1]
        return None

    def set_y(self, data):
        """Set y data"""
        self.xydata[1] = np.array(data, dtype=float)

    x = property(get_x, set_x)
    y = data = property(get_y, set_y)

    def get_roi_param(self, *defaults):
        """Return ROI parameters dataset"""
        i0, i1 = defaults
        imax = len(self.x) - 1

        class ROIParam(gdt.DataSet):
            """Signal ROI parameters"""

            row1 = gdi.IntItem(_("First row index"), default=i0, min=-1, max=imax)
            row2 = gdi.IntItem(_("Last row index"), default=i1, min=-1, max=imax)

        return ROIParam(_("ROI extraction"))

    def get_roi(self):
        """Return signal ROI"""
        return self.metadata.get(ROI_KEY)

    def set_roi(self, roiparam):
        """Set signal ROI"""
        self.metadata[ROI_KEY] = np.array([roiparam.row1, roiparam.row2])

    roi = property(get_roi, set_roi)


class ImageParam(gdt.DataSet, ObjectItf):
    """Image dataset"""

    def __init__(self, title=None, comment=None, icon=""):
        gdt.DataSet.__init__(self, title, comment, icon)
        self._template = None

    @property
    def size(self):
        """Returns (width, height)"""
        return self.data.shape[1], self.data.shape[0]

    def update_metadata(self, value):
        """Update metadata"""
        self.metadata = {}
        for attr in dir(value):
            if attr != "GroupLength" and not re.match(r"__[\S_]*__$", attr):
                self.metadata[attr] = getattr(value, attr)

    @property
    def template(self):
        """Get template"""
        return self._template

    @template.setter
    def template(self, value):
        """Set template"""
        self.update_metadata(value)
        self._template = value

    @property
    def pixel_spacing(self):
        """Get pixel spacing"""
        if self.template is not None:
            return self.template.PixelSpacing
        return None, None

    @pixel_spacing.setter
    def pixel_spacing(self, value):
        """Set pixel spacing"""
        if self.template is not None:
            dx, dy = value
            self.template.PixelSpacing = [dx, dy]
            self.update_metadata(self.template)

    _tabs = gdt.BeginTabGroup("all")

    _datag = gdt.BeginGroup(_("Data and metadata"))
    data = gdi.FloatArrayItem(_("Data"))
    metadata = gdi.DictItem(_("Metadata"), default={})
    _e_datag = gdt.EndGroup(_("Data and metadata"))

    _unitsg = gdt.BeginGroup(_("Titles and units"))
    title = gdi.StringItem(_("Image title"), default=_("Untitled"))
    _tabs_u = gdt.BeginTabGroup("units")
    _unitsx = gdt.BeginGroup(_("X-axis"))
    xlabel = gdi.StringItem(_("Title"))
    xunit = gdi.StringItem(_("Unit"))
    _e_unitsx = gdt.EndGroup(_("X-axis"))
    _unitsy = gdt.BeginGroup(_("Y-axis"))
    ylabel = gdi.StringItem(_("Title"))
    yunit = gdi.StringItem(_("Unit"))
    _e_unitsy = gdt.EndGroup(_("Y-axis"))
    _unitsz = gdt.BeginGroup(_("Z-axis"))
    zlabel = gdi.StringItem(_("Title"))
    zunit = gdi.StringItem(_("Unit"))
    _e_unitsz = gdt.EndGroup(_("Z-axis"))
    _e_tabs_u = gdt.EndTabGroup("units")
    _e_unitsg = gdt.EndGroup(_("Titles and units"))

    _e_tabs = gdt.EndTabGroup("all")

    def copy_data_from(self, other, dtype=None):
        """Copy data from other dataset instance"""
        self.metadata = other.metadata.copy()
        self.data = np.array(other.data, copy=True, dtype=dtype)
        self.template = other.template

    def set_data_type(self, dtype):
        """Change data type"""
        self.data = np.array(self.data, dtype=dtype)

    def get_roi_param(self, *defaults):
        """Return ROI parameters dataset"""
        shape = self.data.shape
        x0, y0, x1, y1 = defaults
        x0, y0 = max(0, x0), max(0, y0)
        xmax, ymax = shape[1] - 1, shape[0] - 1
        x1, y1 = min(xmax, x1), min(ymax, y1)

        class ROIParam(gdt.DataSet):
            """ROI parameters"""

            row1 = gdi.IntItem(_("First row index"), default=y0, min=-1, max=ymax)
            row2 = gdi.IntItem(_("Last row index"), default=y1, min=-1, max=ymax)
            col1 = gdi.IntItem(_("First column index"), default=x0, min=-1, max=xmax)
            col2 = gdi.IntItem(_("Last column index"), default=x1, min=-1, max=xmax)

        return ROIParam(_("ROI extraction"))

    def get_roi(self):
        """Return image ROI"""
        return self.metadata.get(ROI_KEY)

    def set_roi(self, roiparam):
        """Set signal ROI"""
        self.metadata[ROI_KEY] = np.array(
            [roiparam.col1, roiparam.row1, roiparam.col2, roiparam.row2]
        )

    roi = property(get_roi, set_roi)


# === Factory functions --------------------------------------------------------
def create_signal(
    title,
    x=None,
    y=None,
    dx=None,
    dy=None,
    metadata=None,
    xunit=None,
    yunit=None,
    xlabel=None,
    ylabel=None,
):
    """Create a new Signal object"""
    assert isinstance(title, str)
    signal = SignalParam()
    signal.title = title
    signal.set_xydata(x, y, dx=dx, dy=dy)
    signal.xunit, signal.yunit = xunit, yunit
    signal.xlabel, signal.ylabel = xlabel, ylabel
    signal.metadata = {} if metadata is None else metadata
    return signal


def create_image(
    title,
    data=None,
    metadata=None,
    markers=None,
    circles=None,
    ellipses=None,
    segments=None,
    rectangles=None,
    xunit=None,
    yunit=None,
    zunit=None,
    xlabel=None,
    ylabel=None,
    zlabel=None,
):
    """Create a new Image object"""
    assert isinstance(title, str)
    assert isinstance(data, np.ndarray)
    image = ImageParam()
    image.title = title
    image.data = data
    image.xunit, image.yunit, image.zunit = xunit, yunit, zunit
    image.xlabel, image.ylabel, image.zlabel = xlabel, ylabel, zlabel
    image.metadata = {} if metadata is None else metadata
    for shapes, index in (
        (rectangles, CI_RECTANGLE),
        (circles, CI_CIRCLE),
        (ellipses, CI_ELLIPSE),
        (segments, CI_SEGMENT),
        (markers, CI_MARKER),
    ):
        if shapes is not None:
            for stitle, coords in shapes:
                stitle = stitle if stitle.startswith("_") else "_" + stitle
                image.metadata[stitle] = np.array(list(coords) + [index])
    return image
