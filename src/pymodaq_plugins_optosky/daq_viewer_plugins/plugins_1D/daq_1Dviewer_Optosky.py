import time

import numpy as np
from qtpy import QtCore

from pymodaq_utils.utils import ThreadCommand
from pymodaq_data.data import DataToExport, Axis
from pymodaq_gui.parameter import Parameter

from pymodaq.control_modules.viewer_utility_classes import DAQ_Viewer_base, comon_parameters, main
from pymodaq.utils.data import DataFromPlugins

from pymodaq_plugins_optosky.hardware import optosky_wrapper
from pymodaq_plugins_optosky.hardware.optosky_wrapper import OptoskyController


_SERIALS = optosky_wrapper.list_serials_safe()  # scanned once, when PyMoDAQ loads the plugin


class DAQ_1DViewer_Optosky(DAQ_Viewer_base):
    """ Instrument plugin class for the Optosky ATP/HP2000 spectrometers (1D viewer).

    Wraps the Optosky .NET library (``HP2000_wrapper.dll``) through pythonnet. The spectrum is returned against the
    wavelength axis (nm), restricted to the ``Wavelength range`` setting. The spectrometers connected to the computer
    are listed in the ``Serial number`` setting when the plugin is initialized (``findSpectraMeters``).

    The acquisition is asynchronous: ``grab_data`` starts it and a timer polls the ready flag of the library, so the
    plugin can be stopped during a long exposure.

    Compatible devices: Optosky spectrometers driven by the HP2000 library (SDK V1.5.8).
    Tested: not tested yet on the real instrument against this plugin; the logic comes from ``fail.hardware.optosky``
    which was used on an Optosky spectrometer. PyMoDAQ 5.3.0 target, Windows only.
    Installation: ``pip install pythonnet``; install the Optosky USB driver (SDK folder ``usb_driver``); put the DLLs
    (``HP2000_wrapper.dll``, ``Driver.dll``, ``sp.dll``, ``libusb0.dll``) in ``hardware/optosky_dlls`` or in the
    folder set in the ``DLL folder`` setting.

    Attributes:
    -----------
    controller: OptoskyController
        Python wrapper around the Optosky library.
    """
    supported_platforms = ('win32',)

    params = comon_parameters + [
        {'title': 'DLL folder:', 'name': 'dll_folder', 'type': 'browsepath', 'filetype': False,
         'value': str(optosky_wrapper.DEFAULT_DLL_FOLDER),
         'tip': 'Folder containing HP2000_wrapper.dll and the other Optosky DLLs'},
        {'title': 'Serial number:', 'name': 'serial', 'type': 'list', 'limits': _SERIALS,
         'value': _SERIALS[0] if _SERIALS else '',
         'tip': 'Connected spectrometers, scanned when the plugin is loaded and again at initialization; '
                'the first one is used if empty'},
        {'title': 'Exposure (ms):', 'name': 'exposure', 'type': 'float', 'value': 10., 'min': 0.01,
         'tip': 'The limits are read from the device at initialization'},
        {'title': 'Hardware averaging:', 'name': 'averaging', 'type': 'int', 'value': 1, 'min': 1},
        {'title': 'Wavelength range (nm):', 'name': 'wavelength_range', 'type': 'group', 'children': [
            {'title': 'Min:', 'name': 'wl_min', 'type': 'float', 'value': 227.},
            {'title': 'Max:', 'name': 'wl_max', 'type': 'float', 'value': 1139.},
        ]},
        {'title': 'Processing:', 'name': 'processing', 'type': 'group', 'children': [
            {'title': 'Smoothing (0-4):', 'name': 'smoothing', 'type': 'int', 'value': 0, 'min': 0, 'max': 4},
            {'title': 'Dark subtraction:', 'name': 'darksubtract', 'type': 'bool', 'value': False},
            {'title': 'Non linearity correction:', 'name': 'nonlinearcorrect', 'type': 'bool', 'value': False},
            {'title': 'Wave shape correction:', 'name': 'calibrate', 'type': 'bool', 'value': False},
        ]},
    ]

    POLL_INTERVAL_MS = 5

    def ini_attributes(self):
        self.controller: OptoskyController = None
        self.x_axis: Axis = None
        self._timer: QtCore.QTimer = None
        self._deadline = 0.

    def ini_detector(self, controller=None):
        """Detector communication initialization

        Parameters
        ----------
        controller: (object)
            custom object of a PyMoDAQ plugin (Slave case). None if only one actuator/detector by controller
            (Master case)

        Returns
        -------
        info: str
        initialized: bool
            False if initialization failed otherwise True
        """
        if self.is_master:
            self.controller = OptoskyController(dll_folder=self.settings['dll_folder'])
            serials = self.controller.discover()
            self.settings.child('serial').setLimits(serials)
            if self.settings['serial'] not in serials and serials:
                self.settings.child('serial').setValue(serials[0])
            self.controller.set_exposure(self.settings['exposure'])
            self.controller.averaging = self.settings['averaging']
            self.controller.wavelength_range = self._wavelength_range()
            self._apply_processing()
            self.controller.open(self.settings['serial'])
            initialized = self.controller.online
            lmin, lmax = self.controller.exposure_limits
            if lmin is not None:
                self.settings.child('exposure').setOpts(min=lmin)
            if lmax is not None:
                self.settings.child('exposure').setOpts(max=lmax)
        else:
            self.controller = controller
            initialized = True

        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)

        self.x_axis = Axis(data=self.controller.wavelengths, label='Wavelength', units='nm', index=0)
        self.dte_signal_temp.emit(DataToExport(
            name='optosky',
            data=[DataFromPlugins(name='Spectrum', data=[np.zeros_like(self.controller.wavelengths)],
                                  dim='Data1D', labels=['Intensity'], axes=[self.x_axis])]))

        info = f"Optosky spectrometer {self.controller.serial} ready (found: {serials if self.is_master else ''})"
        return info, initialized

    def _wavelength_range(self):
        return self.settings['wavelength_range', 'wl_min'], self.settings['wavelength_range', 'wl_max']

    def _apply_processing(self):
        proc = self.settings.child('processing')
        self.controller.smoothing = proc['smoothing']
        self.controller.darksubtract = proc['darksubtract']
        self.controller.nonlinearcorrect = proc['nonlinearcorrect']
        self.controller.calibrate = proc['calibrate']

    def close(self):
        """Terminate the communication protocol"""
        if self._timer is not None:
            self._timer.stop()
        if self.is_master and self.controller is not None:
            self.controller.close()

    def grab_data(self, Naverage=1, **kwargs):
        """Start an acquisition and return at once, the data is emitted by :meth:`_poll`

        Parameters
        ----------
        Naverage: int
            Ignored: the averaging is done by the spectrometer, see the ``Hardware averaging`` setting.
        kwargs: dict
            others optionals arguments
        """
        self._start_acquisition()

    def _start_acquisition(self):
        self.controller.start_grab()
        self._deadline = time.monotonic() + 2 * self.controller.acquisition_time + 1
        self._timer.start(self.POLL_INTERVAL_MS)

    def _poll(self):
        """Emit the spectrum when the library says it is ready, otherwise look again shortly"""
        if self.controller.is_ready():
            spectrum = self.controller.read_spectrum()
            self.dte_signal.emit(DataToExport(
                name='optosky',
                data=[DataFromPlugins(name='Spectrum', data=[spectrum], dim='Data1D', labels=['Intensity'],
                                      axes=[self.x_axis])]))
        elif time.monotonic() > self._deadline:
            self.emit_status(ThreadCommand('Update_Status', ['Optosky: timeout waiting for the spectrum, retrying']))
            self._start_acquisition()
        else:
            self._timer.start(self.POLL_INTERVAL_MS)

    def stop(self):
        """Stop polling: the library has no command to abort an acquisition, it ends by itself"""
        if self._timer is not None:
            self._timer.stop()
        return ''

    def commit_settings(self, param: Parameter):
        """Apply the consequences of a change of value in the detector settings

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        if param.name() == 'exposure':
            self.controller.set_exposure(param.value())
        elif param.name() == 'averaging':
            self.controller.set_averaging(param.value())
        elif param.name() in ('smoothing', 'darksubtract', 'nonlinearcorrect', 'calibrate'):
            self._apply_processing()
        elif param.name() in ('wl_min', 'wl_max'):
            self.controller.set_wavelength_range(self._wavelength_range())
            self.x_axis = Axis(data=self.controller.wavelengths, label='Wavelength', units='nm', index=0)


if __name__ == '__main__':
    main(__file__)
