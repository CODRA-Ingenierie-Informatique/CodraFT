# -*- coding: utf-8 -*-
#
# Licensed under the terms of the CECILL License
# (see codraft/__init__.py for details)

"""
Image tools test

Simple image dialog for testing all image tools available in CodraFT
"""

# pylint: disable=invalid-name  # Allows short reference names like x, y, ...

import numpy as np
from guiqwt.builder import make

from codraft.tests.data import create_noisy_2d_gaussian
from codraft.utils.qthelpers import qt_app_context
from codraft.utils.vistools import view_image_items

SHOW = True  # Show test in GUI-based test launcher


def image_tools_test():
    """Image tools test"""
    with qt_app_context():
        data = create_noisy_2d_gaussian((2000, 2000), np.uint16, x0=5.0, y0=-3.0)
        items = [make.image(data, interpolation="nearest", eliminate_outliers=2.0)]
        view_image_items(items)


if __name__ == "__main__":
    image_tools_test()
