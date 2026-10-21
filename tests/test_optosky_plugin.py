"""Behaviour of DAQ_1DViewer_Optosky against a fake controller (no hardware, no .NET DLL).

Written for PyMoDAQ 5.3.0, so it does not use ``pymodaq.utils.plugin_testing``: the plugin is created directly and the
Qt event loop is run until the plugin emits its data.
"""
import numpy as np
import pytest
from qtpy import QtCore

from pymodaq_plugins_optosky.daq_viewer_plugins.plugins_1D import daq_1Dviewer_Optosky as module


class FakeOptosky:
    """Same public interface as OptoskyController; the data is ready after ``polls_needed`` calls of is_ready"""
    def __init__(self, dll_folder=None):
        self.online = False
        self.serial = ''
        self.exposure = 10.
        self.averaging = 1
        self.smoothing = 0
        self.darksubtract = self.nonlinearcorrect = self.calibrate = False
        self.wavelength_range = None
        self.exposure_limits = (0.5, 1000.)
        self.wavelengths = np.linspace(227., 1139., 50)
        self.polls_needed = 3
        self._polls = 0
        self.starts = 0

    def discover(self):
        return ['SN1', 'SN2']

    def open(self, serial=None):
        self.online = True
        self.serial = serial

    def close(self):
        self.online = False

    def set_exposure(self, exposure_ms):
        self.exposure = exposure_ms

    def set_averaging(self, averaging):
        self.averaging = averaging

    def set_wavelength_range(self, wavelength_range):
        self.wavelength_range = wavelength_range
        lmin, lmax = wavelength_range
        full = np.linspace(227., 1139., 50)
        self.wavelengths = full[(full >= lmin) & (full <= lmax)]

    @property
    def acquisition_time(self):
        return self.averaging * self.exposure / 1000

    def start_grab(self):
        self.starts += 1
        self._polls = 0

    def is_ready(self):
        self._polls += 1
        return self._polls >= self.polls_needed

    def read_spectrum(self):
        return np.ones_like(self.wavelengths) * self.exposure


@pytest.fixture
def detector(qapp, monkeypatch):
    monkeypatch.setattr(module, 'OptoskyController', FakeOptosky)
    plugin = module.DAQ_1DViewer_Optosky()
    info, initialized = plugin.ini_detector()
    assert initialized
    yield plugin
    plugin.close()


def grab(plugin, timeout_ms=2000):
    """Start a grab and run the event loop until the plugin emits its data"""
    received = []
    loop = QtCore.QEventLoop()

    def on_data(dte):
        received.append(dte)
        loop.quit()

    plugin.dte_signal.connect(on_data)
    QtCore.QTimer.singleShot(timeout_ms, loop.quit)
    plugin.grab_data()
    loop.exec()
    plugin.dte_signal.disconnect(on_data)
    return received[0] if received else None


def test_serial_list_comes_from_the_device(detector):
    assert detector.settings.child('serial').opts['limits'] == ['SN1', 'SN2']
    assert detector.settings['serial'] == 'SN1'
    assert detector.controller.serial == 'SN1'


def test_exposure_limits_come_from_the_device(detector):
    assert detector.settings.child('exposure').opts['min'] == 0.5
    assert detector.settings.child('exposure').opts['max'] == 1000.


def test_grab_is_asynchronous_and_has_wavelength_axis(detector):
    dte = grab(detector)
    assert dte is not None
    data = dte[0]
    assert data.axes[0].units == 'nm'
    assert data.shape == (50,)
    assert data.axes[0].get_data()[0] == pytest.approx(227.)
    assert detector.controller.starts == 1


def test_stop_cancels_the_polling(detector):
    detector.controller.polls_needed = 10 ** 6
    assert grab(detector, timeout_ms=100) is None  # nothing emitted while the device is busy
    detector.stop()
    assert not detector._timer.isActive()


def test_settings_are_forwarded(detector):
    detector.commit_settings(_set(detector, 'exposure', 25.))
    assert detector.controller.exposure == 25.
    detector.commit_settings(_set(detector, 'averaging', 4))
    assert detector.controller.averaging == 4
    detector.commit_settings(_set(detector, 'darksubtract', True, group='processing'))
    assert detector.controller.darksubtract is True
    detector.commit_settings(_set(detector, 'wl_max', 500., group='wavelength_range'))
    assert detector.controller.wavelengths.max() <= 500.
    assert detector.x_axis.get_data().max() <= 500.


def _set(plugin, name, value, group=None):
    param = plugin.settings.child(group, name) if group else plugin.settings.child(name)
    param.setValue(value)
    return param


def test_close_closes_the_controller(detector):
    controller = detector.controller
    detector.close()
    assert controller.online is False
