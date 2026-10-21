pymodaq_plugins_optosky
#######################

PyMoDAQ plugin for Optosky HP2000 spectrometers (Windows only, through the vendor .NET library and pythonnet).

Instruments
===========

* ``DAQ_1DViewer_Optosky``: spectrum versus wavelength (nm). Settings: serial number, exposure (ms), hardware
  averaging, smoothing, dark subtraction, non linearity correction, calibration.

The vendor DLLs (``HP2000_wrapper.dll``, ``Driver.dll``, ``sp.dll``, ``libusb0.dll``) must be placed in
``src/pymodaq_plugins_optosky/hardware/optosky_dlls`` or in the folder given by the ``DLL folder`` setting.
Spectrometers are discovered by serial number: add yours to ``DEVICES`` in ``hardware/optosky_wrapper.py``.

Tested with an ATP2400 spectrometer on windows 11, pymodaq 5.3.

Development
===========

* Install your plugin in editable mode: ``pip install -e .``
* Check it, without any hardware: ``check_plugin`` (and ``pytest``)
* If you use an AI coding assistant, point it to ``AGENTS.md``: it describes the patterns to follow for instrument
  plugins, Dashboard extensions (``CustomExt``, whenever instruments are involved) and standalone apps
  (``CustomApp``, only if no instruments are needed).


Authors
=======

* Matthieu Guer (m.guer@hw.ac.uk)

.. if needed use this field

    Contributors
    ============

    * First Contributor
    * Other Contributors

.. if needed use this field

  Depending on the plugin type, delete/complete the fields below


Instruments
===========

Below is the list of instruments included in this plugin

Actuators
+++++++++

* **yyy**: control of yyy actuators
* **xxx**: control of xxx actuators

Viewer0D
++++++++

* **yyy**: control of yyy 0D detector
* **xxx**: control of xxx 0D detector

Viewer1D
++++++++

* **yyy**: control of yyy 1D detector
* **xxx**: control of xxx 1D detector


Viewer2D
++++++++

* **yyy**: control of yyy 2D detector
* **xxx**: control of xxx 2D detector


PID Models
==========


Extensions
==========


Installation instructions
=========================

* PyMoDAQ’s version.
* Operating system’s version.
* What manufacturer’s drivers should be installed to make this plugin run?
