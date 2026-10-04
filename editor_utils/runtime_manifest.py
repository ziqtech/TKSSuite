"""Thin runtime archives shared by build validation and app bootstrap."""

RUNTIME_ARCHIVES = (
    "PySide6.lib",
    "QtCore.lib",
    "QtGui.lib",
    "QtWidgets.lib",
    "QtSvg.lib",
    "QtMultimedia.lib",
    "PIL.lib",
)
REQUIRED_RUNTIME_ARCHIVES = (
    "PySide6.lib",
    "QtCore.lib",
    "QtGui.lib",
    "QtWidgets.lib",
    "QtMultimedia.lib",
    "PIL.lib",
)
REQUIRED_RUNTIME_MEMBERS = {
    "PySide6.lib": ("shiboken6/__init__.py", "python3.dll"),
    "QtCore.lib": ("PySide6/QtCore.pyd", "PySide6/Qt6Core.dll"),
    "QtGui.lib": ("PySide6/QtGui.pyd", "PySide6/Qt6Gui.dll"),
    "QtWidgets.lib": ("PySide6/QtWidgets.pyd", "PySide6/Qt6Widgets.dll"),
    "QtMultimedia.lib": (
        "PySide6/QtMultimedia.pyd",
        "PySide6/Qt6Multimedia.dll",
        "PySide6/plugins/multimedia/windowsmediaplugin.dll",
    ),
    "PIL.lib": ("PIL/__init__.py",),
}
