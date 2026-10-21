"""Python wrapper around the Optosky HP2000 .NET library (``HP2000_wrapper.dll``).

Adapted from ``fail.hardware.optosky`` and the SDK manual (ATP2000/3000/5000/8000+ develop package, V1.5.8).
Importing this module never loads the DLLs: pythonnet (``clr``) is imported on the first call to
:func:`discover_serials` or :meth:`OptoskyController.open`, so the plugin stays importable on machines without the
driver.

The acquisition is split in :meth:`~OptoskyController.start_grab`, :meth:`~OptoskyController.is_ready` and
:meth:`~OptoskyController.read_spectrum` because the library acquires in the background (``getSpectrum`` returns at
once and ``getSpectrumDataReadyFlag`` tells when the data can be read).
"""
import sys
from pathlib import Path

import numpy as np

DEFAULT_DLL_FOLDER = Path(__file__).parent  # the vendor DLLs sit next to this file

_wrapper = None


def get_wrapper(dll_folder=None):
    """Load the .NET wrapper once and return the ``HP2000Wrapper`` instance."""
    global _wrapper
    if _wrapper is None:
        import clr  # pythonnet
        folder = str(Path(dll_folder) if dll_folder else DEFAULT_DLL_FOLDER)
        if folder not in sys.path:
            sys.path.append(folder)
        clr.AddReference("HP2000_wrapper")
        from HP2000_wrapper import HP2000Wrapper
        _wrapper = HP2000Wrapper()
    return _wrapper


def _to_str(serial) -> str:
    """The serial is a char[128] in the library: pythonnet gives a str or a sequence of chars"""
    if not isinstance(serial, str):
        serial = ''.join(chr(c) if isinstance(c, int) else str(c) for c in serial)
    return serial.split('\x00')[0].strip()


def discover_serials(dll_folder=None) -> list:
    """Serial numbers of all the connected Optosky spectrometers (``findSpectraMeters``)"""
    wrapper = get_wrapper(dll_folder)
    from HP2000_wrapper import spectrum_device_info
    info = spectrum_device_info()
    result = wrapper.findSpectraMeters(info)  # the struct is passed by reference: pythonnet returns the filled one
    if isinstance(result, tuple):
        result = result[-1]
    if result is not None:
        info = result
    return [_to_str(info.descriptor[i].serial) for i in range(info.length)]


def list_serials_safe(dll_folder=None) -> list:
    """Like :func:`discover_serials` but returns [] instead of raising (no driver, no device, not Windows)"""
    try:
        return discover_serials(dll_folder)
    except Exception:
        return []


class OptoskyController:
    """Controls one Optosky spectrometer. Exposure is in ms, wavelengths in nm."""

    def __init__(self, dll_folder=None):
        self.dll_folder = dll_folder
        self.online = False
        self.serial = ''
        self.exposure = 10.
        self.averaging = 1
        self.smoothing = 0
        self.darksubtract = False
        self.nonlinearcorrect = False
        self.calibrate = False
        self.wavelength_range = None  # (min, max) in nm, None keeps the whole detector
        # ms. The library takes the exposure in us (measured on the device: getSpectrum(10000) is ready after ~10 ms
        # although getAttribute() claims ms) and rejects less than 10 us (getSpectrum(1) fails, SDK manual).
        # getIntegrationTimeMinimum/Maximum return 0 and -1 on this device, so they are not used.
        self.exposure_limits = (0.01, None)
        self._time_factor = 1000  # value passed to the library per ms of exposure
        self._all_wavelengths = np.array([])
        self.wavelengths = np.array([])
        self._crop = None

    def discover(self) -> list:
        return discover_serials(self.dll_folder)

    def open(self, serial=None):
        """Open the spectrometer ``serial`` (the first one found if None)."""
        if self.online:
            self.close()
        devices = self.discover()
        if not devices:
            raise RuntimeError("No Optosky spectrometer found")
        if serial is None or serial == '':
            serial = devices[0]
        elif serial not in devices:
            raise RuntimeError(f"Optosky spectrometer {serial} not found, available: {devices}")

        wrapper = get_wrapper(self.dll_folder)
        if not wrapper.openSpectraMeter():
            raise RuntimeError("Opening the Optosky spectrometer failed")
        try:
            if not wrapper.switchSpectraMeters(serial):
                raise RuntimeError(f"Switching to spectrometer {serial} failed")
            if wrapper.initialize() != 0:
                raise RuntimeError(f"Initialising spectrometer {serial} failed")
            wrapper.setAverage(self.averaging)
            self._all_wavelengths = np.fromiter(wrapper.getWavelength(), float)
            self.set_wavelength_range(self.wavelength_range)
        except Exception:
            wrapper.closeSpectraMeter()
            raise
        self.serial = serial
        self.online = True

    def set_wavelength_range(self, wavelength_range):
        """Keep only the pixels within ``(min, max)`` nm (None keeps all of them)"""
        self.wavelength_range = wavelength_range
        if wavelength_range is None:
            self._crop = np.ones(self._all_wavelengths.shape, dtype=bool)
        else:
            lmin, lmax = wavelength_range
            self._crop = (self._all_wavelengths >= lmin) & (self._all_wavelengths <= lmax)
        self.wavelengths = self._all_wavelengths[self._crop]

    def close(self):
        if not self.online:
            return
        try:
            get_wrapper(self.dll_folder).closeSpectraMeter()
        finally:
            self.online = False
            self.serial = ''

    def set_exposure(self, exposure_ms: float):
        self.exposure = exposure_ms

    def set_averaging(self, averaging: int):
        if self.online:
            get_wrapper(self.dll_folder).setAverage(int(averaging))
        self.averaging = int(averaging)

    @property
    def acquisition_time(self) -> float:
        """Expected duration of one acquisition (s)"""
        return self.averaging * self.exposure / 1000

    def start_grab(self):
        """Start an acquisition in the background; poll :meth:`is_ready` then call :meth:`read_spectrum`"""
        if not self.online:
            raise RuntimeError("Optosky spectrometer is not open")
        if not get_wrapper(self.dll_folder).getSpectrum(int(round(self.exposure * self._time_factor))):
            raise RuntimeError("Starting the acquisition failed, the device may be busy")

    def is_ready(self) -> bool:
        return bool(get_wrapper(self.dll_folder).getSpectrumDataReadyFlag())

    def read_spectrum(self) -> np.ndarray:
        """Processed spectrum, cropped to the wavelength range"""
        wrapper = get_wrapper(self.dll_folder)
        data = wrapper.ReadSpectrum()
        if int(data.valid_flag) != 1:  # SpectrumDataValidFlag.SPECTRUMDATA_VALID, SDK manual
            raise RuntimeError("The spectrum read from the Optosky spectrometer is not valid")
        array = wrapper.dataProcess(data.array, self.smoothing, self.darksubtract, self.nonlinearcorrect,
                                    self.calibrate)
        return np.fromiter(array, float)[self._crop]
